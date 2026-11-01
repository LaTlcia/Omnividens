"""Dark themed time navigation controls; only the viewing port is exposed."""
from __future__ import annotations
from dataclasses import replace
import math
import tkinter as tk

from lilyrex.domain.battle_time import format_remaining, format_remaining_microseconds, parse_remaining
from lilyrex.domain.playback import PlaybackPort, PlaybackStatus

BG, PANEL, TEXT, MUTED, ACCENT = '#16213e', '#23243a', '#e0e0f0', '#8a8fb3', '#00d4ff'


class DarkButton(tk.Label):
    """Keyboard accessible flat control with identical colors on Aqua and Windows."""
    def __init__(self, parent, text: str, command, **kwargs):
        super().__init__(parent, text=text, bg=PANEL, fg=ACCENT,
                         disabledforeground='#626780', font=('Arial', 10, 'bold'),
                         padx=10, pady=5, bd=1, relief=tk.FLAT,
                         takefocus=True, highlightthickness=1,
                         highlightbackground='#3a3b5c', highlightcolor=ACCENT, **kwargs)
        self.command = command
        self.bind('<Button-1>', self._activate)
        self.bind('<Return>', self._activate)
        self.bind('<space>', self._activate)
        self.bind('<Enter>', lambda _: self.config(bg='#2d2e4a') if self['state'] != tk.DISABLED else None)
        self.bind('<Leave>', lambda _: self.config(bg=PANEL))

    def invoke(self):
        if self['state'] != tk.DISABLED:
            return self.command()

    def _activate(self, _event=None) -> str:
        self.invoke()
        return 'break'

    def set_enabled(self, enabled: bool) -> None:
        self.config(state=tk.NORMAL if enabled else tk.DISABLED,
                    cursor='hand2' if enabled else '', bg=PANEL, takefocus=enabled)


class PlaybackControls:
    def __init__(self, parent, playback: PlaybackPort | None):
        self.playback = playback
        self.dialog = self.speed_dialog = None
        self.input_var = self.error_var = None
        self.speed_input_var = self.speed_error_var = None
        self.speed_entry = None
        self._last_status: PlaybackStatus | None = None
        self.row = tk.Frame(parent, bg=BG)
        self.row.pack()
        self.btn_step_backward = DarkButton(self.row, '后退一步', lambda: self.step(-1))
        self.btn_step_backward.pack(side=tk.LEFT, padx=(0, 6))
        self.btn_step_forward = DarkButton(self.row, '前进一步', lambda: self.step(1))
        self.btn_step_forward.pack(side=tk.LEFT, padx=(0, 6))
        self.btn_seek = DarkButton(self.row, '跳转时间', self.open_dialog)
        self.btn_seek.pack(side=tk.LEFT, padx=(0, 12))
        self.countdown = tk.Label(self.row, text='--:--', font=('Arial', 18, 'bold'),
                                  fg='#ffdd00', bg=BG)
        self.countdown.pack(side=tk.LEFT)
        self.countdown.bind('<Button-1>', self._pause_click)
        self.countdown.bind('<Return>', self._pause_click)
        self.btn_live = DarkButton(self.row, '回到直播', self.return_live)
        self.btn_live.pack(side=tk.LEFT, padx=(12, 0))
        self.btn_speed = DarkButton(self.row, '1×', self.open_speed_dialog)
        self.btn_speed.pack(side=tk.LEFT, padx=(6, 0))
        self.status_label = tk.Label(parent, text='', bg=BG, fg=MUTED,
                                     font=('Arial', 9), height=1)
        self.status_label.pack()
        self.status_label.bind('<Button-1>', lambda _: self.open_dialog())
        self._root = self.row.winfo_toplevel()
        self._space_binding = self._root.bind('<space>', self._space_key, add='+')
        self.refresh()

    def refresh(self) -> None:
        status = self.playback.status() if self.playback is not None else None
        if status is not None and status.display_remaining_seconds is not None:
            text = format_remaining_microseconds(status.display_remaining_seconds)
            if text != getattr(self, '_last_countdown', None):
                self.countdown.config(text=text)
                self._last_countdown = text
        else:
            self._last_countdown = None
        # Clock-only ticks must not reconfigure buttons, dialogs or status text.
        controls_status = (replace(status, display_remaining_seconds=
            0.0 if status.display_remaining_seconds is not None else None) if status else None)
        if controls_status == self._last_status and status is not None:
            return
        self._last_status = controls_status
        self.btn_step_backward.set_enabled(status is not None and status.can_step_backward)
        self.btn_step_forward.set_enabled(status is not None and status.can_step_forward)
        can_pause = status is not None and status.can_pause
        self.countdown.config(cursor='hand2' if can_pause else '', takefocus=can_pause)
        self.btn_seek.set_enabled(status is not None and status.available_remaining is not None)
        self.btn_live.set_enabled(status is not None and status.mode != 'replay'
                                  and (status.mode == 'history' or status.seeking))
        can_set_speed = status is not None and status.can_set_speed
        self.btn_speed.set_enabled(can_set_speed)
        self.btn_speed.config(text='不限速' if status is not None and status.unlimited
                              else f'{status.speed:g}×' if status is not None else '1×')
        if self.speed_dialog is not None and not can_set_speed:
            self.close_speed_dialog()
        if status is None:
            self.status_label.config(text='')
            return
        text = self._status_text(status)
        if status.display_remaining_seconds is not None:
            text += ' · 接收时间推算'
        self.status_label.config(text=text,
                                 fg=ACCENT if status.mode == 'live' else MUTED,
                                 cursor='hand2' if status.available_remaining is not None else '')
        if self.dialog is not None:
            self.range_label.config(text=self._range_text(status))
            self.notice_label.config(text=status.notice)

    @staticmethod
    def _status_text(status: PlaybackStatus) -> str:
        mode = {'live': '直播', 'history': '回看', 'replay': '回放'}[status.mode]
        if status.seeking:
            return mode + ' · 正在跳转…'
        if (status.available_remaining is None and not status.source_complete
                and not status.can_pause and not status.paused):
            return mode + ' · 正在加载…'
        if status.paused:
            action = ' · ' + status.action_label if status.action_label else ''
            hint = ' · 点击时间或空格继续' if status.can_pause else ''
            return mode + ' · 已暂停' + action + hint
        if status.at_end and status.mode == 'replay':
            return mode + ' · 已结束，可跳转'
        # Full notices belong in the dialog; keep the header exactly one line.
        hint = ' · 点击时间或空格暂停' if status.can_pause else ''
        return mode + (' · 时间提示，点击查看' if status.notice else '') + hint

    def toggle_pause(self) -> None:
        if self.playback is None or not self.playback.status().can_pause:
            return
        try:
            self.playback.toggle_pause()
        except ValueError as exc:
            self.status_label.config(text=str(exc))
            return
        self.refresh()

    def _pause_click(self, _event=None) -> str:
        self.toggle_pause()
        return 'break'

    def _space_key(self, event) -> str | None:
        if (self.dialog is not None or self.speed_dialog is not None
                or event.widget.winfo_toplevel() is not self._root):
            return None
        if isinstance(event.widget, DarkButton) or event.widget.winfo_class() in {
                'Entry', 'TEntry', 'Text', 'Spinbox', 'TSpinbox', 'TCombobox',
                'Button', 'TButton', 'Checkbutton', 'TCheckbutton', 'Radiobutton',
                'TRadiobutton', 'Listbox', 'Scale', 'TScale'}:
            return None
        if self.playback is None or not self.playback.status().can_pause:
            return None
        self.toggle_pause()
        return 'break'

    def step(self, direction: int) -> None:
        if self.playback is None:
            return
        status = self.playback.status()
        if not (status.can_step_backward if direction == -1 else status.can_step_forward):
            return
        try:
            self.playback.step(direction)
        except ValueError as exc:
            self.status_label.config(text=str(exc))
            return
        self.refresh()

    @staticmethod
    def _range_text(status: PlaybackStatus) -> str:
        if status.available_remaining is None:
            return '暂无可跳转的数据'
        lower, upper = status.available_remaining
        return f'可用剩余时间：{format_remaining(lower)} ～ {format_remaining(upper)}'

    def open_dialog(self) -> None:
        if self.playback is None:
            return
        status = self.playback.status()
        if status.available_remaining is None:
            return
        self.close_speed_dialog()
        if self.dialog is not None:
            self.dialog.lift()
            self.entry.focus_set()
            return
        self.dialog = dialog = tk.Toplevel(self.row)
        dialog.title('跳转时间')
        dialog.configure(bg=BG)
        dialog.transient(self.row.winfo_toplevel())
        dialog.resizable(False, False)
        tk.Label(dialog, text='比赛剩余时间', bg=BG, fg=TEXT,
                 font=('Arial', 12, 'bold')).pack(padx=24, pady=(18, 8))
        current = status.remaining_seconds
        self.input_var = tk.StringVar(value=format_remaining(current) if current is not None else '')
        self.entry = tk.Entry(dialog, textvariable=self.input_var, width=12,
                              justify=tk.CENTER, font=('Arial', 18, 'bold'), bg=PANEL,
                              fg='#ffdd00', insertbackground=TEXT, relief=tk.FLAT,
                              highlightthickness=1, highlightbackground='#3a3b5c', highlightcolor=ACCENT)
        self.entry.pack(padx=24, ipady=5)
        tk.Label(dialog, text='MM:SS，例如 12:30', bg=BG, fg=MUTED,
                 font=('Arial', 10)).pack(pady=(6, 8))
        self.range_label = tk.Label(dialog, text=self._range_text(status), bg=BG,
                                    fg=TEXT, font=('Arial', 10))
        self.range_label.pack(padx=24)
        self.notice_label = tk.Label(dialog, text=status.notice, bg=BG, fg=MUTED,
                                     wraplength=340, font=('Arial', 10))
        self.notice_label.pack(padx=20, pady=(6, 0))
        self.error_var = tk.StringVar(value='')
        tk.Label(dialog, textvariable=self.error_var, bg=BG, fg='#ff7d9c',
                 wraplength=340, font=('Arial', 10)).pack(padx=16, pady=8)
        actions = tk.Frame(dialog, bg=BG)
        actions.pack(pady=(0, 16))
        DarkButton(actions, '取消', self.close_dialog).pack(side=tk.LEFT, padx=6)
        self.btn_confirm = DarkButton(actions, '跳转', self.submit)
        self.btn_confirm.pack(side=tk.LEFT, padx=6)
        dialog.bind('<Return>', lambda _: self.submit())
        dialog.bind('<Escape>', lambda _: self.close_dialog())
        dialog.protocol('WM_DELETE_WINDOW', self.close_dialog)
        dialog.update_idletasks()
        root = self.row.winfo_toplevel()
        x = root.winfo_rootx() + (root.winfo_width() - dialog.winfo_reqwidth()) // 2
        y = root.winfo_rooty() + 100
        dialog.geometry(f'+{max(0, x)}+{max(0, y)}')
        self.entry.focus_set()
        self.entry.selection_range(0, tk.END)

    def open_speed_dialog(self) -> None:
        if self.playback is None or not self.playback.status().can_set_speed:
            return
        if self.speed_dialog is not None:
            self.speed_dialog.lift()
            self.speed_entry.focus_set()
            return
        self.close_dialog()
        status = self.playback.status()
        self.speed_dialog = dialog = tk.Toplevel(self.row)
        dialog.title('播放倍速')
        dialog.configure(bg=BG)
        dialog.transient(self.row.winfo_toplevel())
        dialog.resizable(False, False)
        tk.Label(dialog, text='播放倍速', bg=BG, fg=TEXT,
                 font=('Arial', 12, 'bold')).pack(padx=24, pady=(18, 8))
        presets = tk.Frame(dialog, bg=BG)
        presets.pack(padx=18, pady=(0, 10))
        for index, speed in enumerate((0.1, 0.25, 0.5, 1, 2, 4, 8, 16)):
            button = DarkButton(presets, f'{speed:g}×',
                                lambda value=speed: self._select_speed(value))
            if speed == status.speed:
                button.config(relief=tk.SUNKEN, highlightbackground=ACCENT)
            button.grid(row=index // 4, column=index % 4, padx=3, pady=3, sticky='ew')
        tk.Label(dialog, text='自定义倍率（正数，支持慢放）', bg=BG, fg=MUTED,
                 font=('Arial', 10)).pack(padx=20)
        self.speed_input_var = tk.StringVar(value=str(status.speed))
        self.speed_entry = tk.Entry(dialog, textvariable=self.speed_input_var, width=12,
                                   justify=tk.CENTER, font=('Arial', 18, 'bold'), bg=PANEL,
                                   fg=ACCENT, insertbackground=TEXT, relief=tk.FLAT,
                                   highlightthickness=1, highlightbackground='#3a3b5c',
                                   highlightcolor=ACCENT)
        self.speed_entry.pack(padx=24, pady=(6, 0), ipady=5)
        self.speed_error_var = tk.StringVar(value='')
        tk.Label(dialog, textvariable=self.speed_error_var, bg=BG, fg='#ff7d9c',
                 wraplength=340, font=('Arial', 10)).pack(padx=16, pady=8)
        actions = tk.Frame(dialog, bg=BG)
        actions.pack(pady=(0, 16))
        DarkButton(actions, '取消', self.close_speed_dialog).pack(side=tk.LEFT, padx=6)
        DarkButton(actions, '应用', self.submit_speed).pack(side=tk.LEFT, padx=6)
        dialog.bind('<Return>', lambda _: self.submit_speed())
        dialog.bind('<Escape>', lambda _: self.close_speed_dialog())
        dialog.protocol('WM_DELETE_WINDOW', self.close_speed_dialog)
        dialog.update_idletasks()
        root = self.row.winfo_toplevel()
        x = root.winfo_rootx() + (root.winfo_width() - dialog.winfo_reqwidth()) // 2
        dialog.geometry(f'+{max(0, x)}+{max(0, root.winfo_rooty() + 100)}')
        self.speed_entry.focus_set()
        self.speed_entry.selection_range(0, tk.END)

    def _select_speed(self, speed: float) -> None:
        if self.speed_input_var is not None:
            self.speed_input_var.set(f'{speed:g}')
            self.submit_speed()

    def submit_speed(self) -> None:
        if self.playback is None or self.speed_input_var is None:
            return
        try:
            if not self.playback.status().can_set_speed:
                raise ValueError('当前状态不能调节倍速')
            try:
                speed = float(self.speed_input_var.get().strip())
            except ValueError:
                raise ValueError('倍速必须是有限正数，例如0.25、1或2') from None
            if not math.isfinite(speed) or speed <= 0:
                raise ValueError('倍速必须是有限正数，例如0.25、1或2')
            self.playback.set_speed(speed)
        except ValueError as exc:
            self.speed_error_var.set(str(exc))
            return
        self.close_speed_dialog()
        self.refresh()

    def close_speed_dialog(self) -> None:
        if self.speed_dialog is not None:
            dialog, self.speed_dialog = self.speed_dialog, None
            try:
                dialog.destroy()
            except tk.TclError:
                pass
        self.speed_input_var = self.speed_error_var = self.speed_entry = None

    def submit(self) -> None:
        if self.playback is None or self.input_var is None:
            return
        try:
            seconds = parse_remaining(self.input_var.get())
            self.playback.seek_remaining(seconds)
        except ValueError as exc:
            self.error_var.set(str(exc))
            return
        self.close_dialog()
        self.refresh()

    def return_live(self) -> None:
        if self.playback is None:
            return
        self.playback.return_live()
        self.close_dialog()
        self.close_speed_dialog()
        self.refresh()

    def close_dialog(self) -> None:
        if self.dialog is not None:
            dialog, self.dialog = self.dialog, None
            try:
                dialog.destroy()
            except tk.TclError:
                pass  # The root may already have destroyed its transient children.
        self.input_var = self.error_var = None

    def destroy(self) -> None:
        self.close_dialog()
        self.close_speed_dialog()
        if self._space_binding is not None:
            binding, self._space_binding = self._space_binding, None
            try:
                self._root.unbind('<space>', binding)
            except tk.TclError:
                pass
