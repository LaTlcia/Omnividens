"""Read-only, scrollable calculation text using the existing tooltip colors."""
from __future__ import annotations

import tkinter as tk
from typing import Any


def wheel_units(delta: int | float, button: int | None = None) -> int:
    """Normalize macOS/Windows wheel deltas and X11 wheel buttons."""
    if button in (4, 5):
        return -1 if button == 4 else 1
    if not delta:
        return 0
    return (-1 if delta > 0 else 1) * max(1, int(abs(delta) / 120))


class FormulaView:
    """Keep the full service-provided text; scrolling never changes playback."""

    def __init__(self, parent: tk.Misc, theme: Any, *, height: int) -> None:
        self.frame = tk.Frame(parent, bg=theme.bg, height=height, takefocus=False)
        self.frame.pack_propagate(False)
        self.text = tk.Text(
            self.frame, wrap=tk.WORD, width=1, height=1, borderwidth=0,
            highlightthickness=0, bg=theme.bg, fg=theme.text,
            font=(theme.font_name, 9), padx=8, pady=5, spacing3=5,
            selectbackground=theme.header, selectforeground=theme.text,
            takefocus=False, cursor="arrow", exportselection=False,
        )
        # Native Aqua scrollbars ignore Tk colors. A local canvas keeps the
        # same dark track/thumb on macOS, Windows and X11 without global styles.
        self.scrollbar = tk.Canvas(self.frame, width=11, borderwidth=0,
                                   highlightthickness=0, bg=theme.bg, takefocus=False)
        self._thumb_color = theme.border
        self._scroll_range = (0.0, 1.0)
        self._drag_offset = 0.0
        self.scrollbar.bind('<Configure>', lambda _event: self._draw_thumb())
        self.scrollbar.bind('<Button-1>', self._start_drag)
        self.scrollbar.bind('<B1-Motion>', self._drag)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.text.configure(yscrollcommand=self._set_scroll)
        for widget in (self.frame, self.text, self.scrollbar):
            for event in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                widget.bind(event, self._wheel)
        # Text is read-only and this popup must never handle the game's space
        # shortcut. Wheel/scrollbar access does not take keyboard focus.
        self.text.bind("<KeyPress>", lambda _event: "break")
        self.text.bind("<Button-1>", lambda _event: "break")

    def set_content(self, paragraphs: tuple[str, ...], position: float = 0.0) -> None:
        self.text.configure(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", "\n\n".join(paragraphs))
        self.text.configure(state=tk.DISABLED)
        self.text.update_idletasks()
        self.text.yview_moveto(position)

    def _wheel(self, event: Any) -> str:
        units = wheel_units(getattr(event, "delta", 0), getattr(event, "num", None))
        if units:
            self.text.yview_scroll(units, "units")
        return "break"

    def _set_scroll(self, first: str, last: str) -> None:
        self._scroll_range = float(first), float(last)
        self._draw_thumb()

    def _draw_thumb(self) -> tuple[float, float]:
        height = self.scrollbar.winfo_height()
        first, last = self._scroll_range
        top, bottom = first * height, last * height
        self.scrollbar.delete('thumb')
        self.scrollbar.create_rectangle(3, top, 9, bottom, outline='',
                                        fill=self._thumb_color, tags='thumb')
        return top, bottom

    def _start_drag(self, event: Any) -> str:
        top, bottom = self._draw_thumb()
        self._drag_offset = event.y - top if top <= event.y <= bottom else (bottom - top) / 2
        return self._drag(event)

    def _drag(self, event: Any) -> str:
        fraction = (event.y - self._drag_offset) / max(1, self.scrollbar.winfo_height())
        self.text.yview_moveto(max(0.0, min(1.0, fraction)))
        return 'break'
