"""Tk window, driven by the application; no network or file dependencies."""
from __future__ import annotations
from collections import deque
import random
import time

from lilyrex.domain.ports import ControlPort
from lilyrex.domain.playback import PlaybackPort
from lilyrex.domain.battle_time import format_remaining
from .battle_footer import BattleFooter
from .damage_tooltip import DamageTooltip, TooltipTheme
from .front_card import PlayerCardPanel
from .icons import IconBank
from .layout import WindowLayout
from .presenter import BattlePresenter
from .rear_card import RearCardPanel
from .theme import *
from .view_models import BattleView, UiResources


class GameStyleGUI(WindowLayout, BattleFooter):
    def __init__(self, root, session, resources: UiResources, controls: ControlPort,
                 room_id: str = "", hover_delay_ms: int = 180,
                 watcher_user_id: int = 0, preview_enabled: bool = True,
                 playback: PlaybackPort | None = None):
        self.root, self.session, self.resources = root, session, resources
        self.playback = playback
        self.presenter = BattlePresenter(session, watcher_user_id)
        self.root.title("⚔️ GVG Battle Monitor ⚔️")
        self.root.geometry(f"{min(1920, root.winfo_screenwidth())}x"
                           f"{min(1080, root.winfo_screenheight() - 60)}+0+0")
        self.root.configure(bg="#1a1a2e")
        self.control_pool, self.room_id = controls, room_id
        self.last_points = (-1, -1)
        self.view_swapped = False
        self.icons = IconBank(resources)
        self.icon_size, self._max_rows = ICON, 4
        self.hp_log = {}
        self._clock = None
        self.deck = session.deck
        self.selected_uid = None
        self._users_by_uid, self._panel_by_uid = {}, {}
        self.damage_preview = session.preview
        self.damage_tooltip = None
        self._damage_hover = None
        self._last_revision = -1
        self._destroyed = False
        self._status_job = None
        self.setup_ui()
        if self.damage_preview is not None and preview_enabled:
            self.damage_tooltip = DamageTooltip(root, theme=TooltipTheme(),
                                                icon_provider=lambda a: self.icons.attribute(a, 18),
                                                delay_ms=hover_delay_ms)
        self.deck_console.on_hover = self._on_damage_hover
        self.deck_console.on_hover_end = self._hide_damage_preview
        self.deck_console.on_hover_leave = self._leave_damage_preview
        root.bind("<Destroy>", self._on_destroy, add="+")
        self.poll_cmd_status()

    def refresh(self, force: bool = False) -> None:
        """Render the newest presentation after every event has been consumed."""
        if self._destroyed:
            return
        self.playback_controls.refresh()
        self._refresh_control_state()
        view = self.presenter.view()
        if view is not None and (force or view.revision != self._last_revision):
            self._render_view(view)
            self._last_revision = view.revision
        self.on_hp_change(self.session.drain_hp_events())

    def bind_session(self, session) -> None:
        """Atomically bind all consumers to the newly committed viewing state."""
        if session is self.session:
            return
        self._hide_damage_preview()
        continues = getattr(session, 'continues', None)
        if not callable(continues) or not continues(self.session):
            self.hp_log.clear()
        for column in self.cols:
            for panel in column['panels']:
                if hasattr(panel, 'cancel_hp_animation'):
                    panel.cancel_hp_animation()
                panel.hide()
        self.session = self.presenter.session = session
        self.deck, self.damage_preview = session.deck, session.preview
        self._last_revision = -1
        self.last_points = (-1, -1)
        self._clock = None
        self._users_by_uid, self._panel_by_uid = {}, {}
        self.deck_console.show(None, None, self.deck)
        if self.presenter.view() is None:
            self.selected_uid = None
            self.lbl_countdown.config(text='--:--')
            self.lbl_guild_left.config(text='Guild A')
            self.lbl_guild_right.config(text='Guild B')
            self.lbl_score_left.config(text='0')
            self.lbl_score_right.config(text='0')
            self.lbl_wr_a.config(text='WR-A: -')
            self.lbl_wr_b.config(text='WR-B: -')
            self.update_bottom_info((), (), {}, 0)
        self.refresh(force=True)

    def _render_view(self, view: BattleView) -> None:
        guilds = view.guilds
        if len(guilds) < 2:
            return
        left, right = (guilds[1], guilds[0]) if self.view_swapped else guilds[:2]
        a, b = left['point'], right['point']
        self.lbl_guild_left.config(text=f"Guild {left['guildDataId']}")
        self.lbl_guild_right.config(text=f"Guild {right['guildDataId']}")
        self.lbl_score_left.config(text=f"{a:,}")
        self.lbl_score_right.config(text=f"{b:,}")
        self._clock = (view.elapsed_seconds, time.monotonic())
        remaining = max(0, BATTLE_SECONDS - view.elapsed_seconds)
        self.lbl_countdown.config(text=format_remaining(remaining))
        if (a, b) != self.last_points:
            self.lbl_wr_a.config(text=f"WR A: {self.calc_wr(a, b, 'A')}")
            self.lbl_wr_b.config(text=f"WR B: {self.calc_wr(a, b, 'B')}")
            self.last_points = a, b
        columns = [[], [], [], []]
        for player in view.players:
            side = 0 if player['guildDataId'] == left['guildDataId'] else 2
            if player['guildDataId'] not in (left['guildDataId'], right['guildDataId']):
                continue
            index = (1 if player['partySequence'] == 1 else 0) if side == 0 else (2 if player['partySequence'] == 1 else 3)
            columns[index].append(player)
        for column in columns:
            column.sort(key=lambda p: p['memberRank'])
        rows = max(4, len(columns[1]), len(columns[2]))
        if rows != self._max_rows:
            self._max_rows = rows
            self._fit_icon_size()
        by_uid = {}
        for index, players in enumerate(columns):
            column = self.cols[index]
            panels = column['panels']
            while len(panels) < len(players):
                panel_type = RearCardPanel if index in (0, 3) else PlayerCardPanel
                panels.append(panel_type(column['frame'], column['color'],
                                         control_pool=self.control_pool, room_provider=lambda: self.room_id,
                                         icons=self.icons, icon_size=self.icon_size, hp_log=self.hp_log))
            for panel, player in zip(panels, players):
                panel.on_select = self.select_player
                panel.update(player, view.players, view.stacks, {})
                panel.set_selected(player['userId'] == self.selected_uid)
                by_uid[player['userId']] = panel
            for panel in panels[len(players):]:
                panel.hide()
        self._panel_by_uid = by_uid
        self._users_by_uid = {p['userId']: p for p in view.players}
        if self.selected_uid is not None:
            if self.selected_uid not in self._users_by_uid:
                self.select_player(self.selected_uid)
            else:
                if self.deck_console.uid != self.selected_uid:
                    self.deck_console.show(self.selected_uid, self._users_by_uid[self.selected_uid], self.deck)
                else:
                    self.deck_console.set_user(self._users_by_uid[self.selected_uid])
                    self.deck_console.redraw()
        self.update_bottom_info(view.orders, view.pending_orders, view.ball, view.server_time)
        self._refresh_damage_preview()

    def select_player(self, uid):
        self.selected_uid = None if uid == self.selected_uid else uid
        for player_id, panel in self._panel_by_uid.items():
            panel.set_selected(player_id == self.selected_uid)
        self.deck_console.show(self.selected_uid, self._users_by_uid.get(self.selected_uid), self.deck)

    def swap_view(self):
        self.view_swapped = not self.view_swapped
        self.refresh(force=True)

    @staticmethod
    def calc_wr(a, b, order):
        # Preserve the original rough UI simulation, independent of damage math.
        wins = 0
        for _ in range(50):
            left, right = a, b
            for side in order:
                fraction = random.uniform(.15, .30)
                if side == 'A':
                    left, right = left + right * fraction, right * (1 - fraction)
                else:
                    left, right = left * (1 - fraction), right + left * fraction
            wins += left > right
        return f"{wins * 2}%"

    def _on_damage_hover(self, uid, card, skill, x, y):
        if self.damage_tooltip is None or self.damage_preview is None:
            return
        known = self.damage_preview.catalog.skill(card, skill)
        if known is None and self.resources.card_data.get(card, ('', 0, 0))[2] not in (1, 2, 3, 4):
            self._hide_damage_preview()
            return
        self._damage_hover = uid, card
        def provide():
            current_skill = self.deck.view(uid)[0].get(card, 0)
            return self.damage_preview.preview(uid, card, current_skill)
        self.damage_tooltip.request((uid, card), provide, x, y)

    def _hide_damage_preview(self):
        self._damage_hover = None
        if self.damage_tooltip is not None:
            self.damage_tooltip.hide()

    def _leave_damage_preview(self):
        if self.damage_tooltip is not None:
            self.damage_tooltip.leave()

    def _refresh_damage_preview(self):
        if self.damage_tooltip is None or self._damage_hover is None:
            return
        uid, card = self._damage_hover
        if uid != self.selected_uid or card not in self.deck.view(uid)[0]:
            self._hide_damage_preview()
        else:
            self.damage_tooltip.refresh()

    def poll_cmd_status(self):
        if self._destroyed:
            return
        self._refresh_control_state()
        self._status_job = self.root.after(1000, self.poll_cmd_status)

    def _refresh_control_state(self):
        for column in self.cols:
            for panel in column['panels']:
                panel.refresh_control_state()
        if not getattr(self.control_pool, 'enabled', True):
            mode = self.playback.status().mode if self.playback is not None else 'replay'
            label = 'REPLAY' if mode == 'replay' else '回看'
            self.lbl_cmd_status.config(text=f"{label} · 控制已禁用", fg="#aab0dc")
        else:
            live, opened = self.control_pool.counts()
            self.lbl_cmd_status.config(text="BOTS: idle" if not opened else f"BOTS: {live}/{opened} connected",
                                       fg="#00ff88" if opened and live == opened else "#888888")

    def _battle_clock(self):
        if self._clock is None:
            return "--:--"
        if self.playback is not None and self.playback.status().mode != 'live':
            return format_remaining(max(0, BATTLE_SECONDS - self.session.snapshot.elapsed_seconds))
        elapsed, observed = self._clock
        remaining = max(0, BATTLE_SECONDS - elapsed - min(time.monotonic() - observed, 1.5))
        return format_remaining(remaining)

    def on_hp_change(self, changes):
        clock = self._battle_clock()
        for uid, kind, value in changes:
            self.hp_log.setdefault(uid, deque(maxlen=HP_LOG_LEN)).appendleft((kind, value, clock))
            panel = self._panel_by_uid.get(uid)
            if panel is not None:
                panel.pop_hp(kind, value)

    def _on_destroy(self, event):
        if event.widget is not self.root:
            return
        self._destroyed = True
        if self._status_job is not None:
            self.root.after_cancel(self._status_job)
            self._status_job = None
        if self.damage_tooltip is not None:
            self.damage_tooltip.destroy()
        self.playback_controls.destroy()
