"""Migrated Tk rendering; no networking or file configuration."""
from __future__ import annotations
from .theme import *
from .card_base import CardBase

class RearCardPanel(CardBase):
    """Compact card for 後衛 — never damaged or healed, so no HP, buffs or hit list:

    header : job accent | card-type icon | #rank | name | last card's attribute
    row 2  : bot buttons                          →味方#n 敵#n
    row 3  : MP bar (0-400)                       stacks (≤3 icons)
    Fixed size; icon fitting and hit pops don't apply.
    """
    H = 74
    ICON_EDGE = 16
    ROW_BTN, ROW_MP = 35, 59
    BTN_W = 19
    NAME_FONT = ("Arial", 10, "bold")

    def __init__(self, parent, bg_color, control_pool=None, room_provider=None, icons=None, **_ignored):
        self._init_card(parent, bg_color, control_pool, room_provider, icons, self.ICON_EDGE, self.H)
        self._init_mp()
        self.stack_slots = [self._icon_slot() for _ in range(MAX_STACKS)]
        self.i_target = self.card.create_text(0, 0, anchor="e", font=F_SMALL)

    def set_icon_size(self, s):
        pass

    def pop_hp(self, kind, value):
        pass

    def _render(self):
        user, stack_data = self._last
        W = self.W
        self._render_header(user, user['hp'] <= 0, W - 6)
        self._render_buttons(8, self.ROW_BTN)
        self._render_target(W - 6, self.ROW_BTN, user)
        sx = W - 6 - MAX_STACKS * (self.s + ICON_GAP) + ICON_GAP     # stacks at the right end of the MP row
        self._render_mp(8, sx - 6, self.ROW_MP - 6, self.ROW_MP + 6, user['sp'])
        self._render_stacks(sx, self.ROW_MP - self.s // 2, user, stack_data, ("Arial", 8, "bold"))


