"""Migrated Tk rendering; no networking or file configuration."""
from __future__ import annotations
import tkinter as tk
from .theme import *
from .card_base import CardBase
from lilyrex.domain.deck_tracker import DECK_MAX

class DeckConsole:
    """控制台 記牌 view of one player: a box per memoria (card name + last skill used),
    bright = still to come this cycle, dim = used, gold edge = the latest one."""
    ROW_MIN, ROW_MAX = 24, 34
    BG = "#16213e"
    F_CARD = ("Arial", 9, "bold")
    F_SKILL = ("Arial", 8)
    F_HEAD = ("Arial", 11, "bold")

    def __init__(self, parent, icons):
        self.icons = icons
        self.uid = self.user = self.tracker = None
        self._head_key = None
        self.on_hover = None
        self.on_hover_end = None
        self.on_hover_leave = None
        self._hit_rows = []
        self._hit_row_height = self.ROW_MIN
        self._hover_y = None
        self.head = tk.Canvas(parent, height=46, bg=self.BG, highlightthickness=0)
        self.head.pack(fill=tk.X, padx=6)
        self.body = tk.Canvas(parent, bg=self.BG, highlightthickness=0)
        self.body.pack(fill=tk.BOTH, expand=True, padx=6, pady=(2, 6))
        self.body.bind("<Configure>", lambda e: (self._end_hover(), self.redraw()))
        self.body.bind("<Motion>", self._on_motion)
        self.body.bind("<Leave>", lambda e: self._end_hover(leaving=True))

    def _end_hover(self, *, leaving=False):
        self._hover_y = None
        callback = self.on_hover_leave if leaving and self.on_hover_leave else self.on_hover_end
        if callback:
            callback()

    def _on_motion(self, event):
        self._hover_y = event.y
        row = self._hit_row_height
        index = int(self.body.canvasy(event.y)) // row
        if (self.uid is None or not 0 <= index < len(self._hit_rows)
                or event.y % row >= row - 2 or self._hit_rows[index] is None):
            self._end_hover()
            return
        if self.on_hover:
            card, skill = self._hit_rows[index]
            self.on_hover(self.uid, card, skill, event.x_root, event.y_root)

    def show(self, uid, user, tracker):
        self._end_hover()
        self.uid, self.user, self.tracker = uid, user, tracker
        self._head_key = None
        self.redraw()

    def set_user(self, user):
        """Latest frame's data for the shown player (name/rank/job may change)."""
        self.user = user
        self._draw_head()

    def redraw(self):
        self._draw_head()
        self._draw_body()

    def _draw_head(self):
        h, u = self.head, self.user
        if self.uid is None:
            key = None
        else:
            cards, used, size, cycle, _, clean = self.tracker.view(self.uid)
            job = self.icons.resources.chara_data.get(str((u or {}).get('characterJobMstId')), {}).get('mainCardType', '')
            key = ((u or {}).get('name'), (u or {}).get('memberRank'), job, len(cards), len(used), size, cycle, clean)
        if key == self._head_key:
            return
        self._head_key = key
        h.delete("all")
        W = max(h.winfo_width(), 200)
        if self.uid is None:
            h.create_text(4, 23, anchor="w", text="点击玩家卡片查看记牌", fill="#6c6f93", font=self.F_HEAD)
            return
        name, rank, job, n_cards, n_used, size, cycle, clean = key
        color = readable(PLAYER_JOB_COLOR.get(job, "#9e9e9e"))
        ct = CARD_TYPE_ID.get(job)
        if ct:
            h.create_image(2, 13, anchor="w", image=self.icons.card_type(ct, color=color))
        title = f"#{rank if rank is not None else '?'} {name or self.uid}"
        h.create_text(26, 13, anchor="w", text=CardBase._fit(title, self.F_HEAD, W - 30),
                      fill="#ffffff", font=self.F_HEAD)
        total = size or DECK_MAX
        if clean:
            info = f"第{cycle or '?'}轮   已用 {n_used}/{total}   剩 {total - n_used}   已见 {n_cards}"
        else:                              # joined mid-cycle: still working out where cycles break
            info = f"中途加入·推算轮次中   已用≥{n_used}   已见 {n_cards}"
        h.create_text(2, 35, anchor="w", font=F_SMALL, fill="#aab0dc", text=info)

    def _draw_body(self):
        b = self.body
        b.delete("all")
        previous_rows, previous_height = self._hit_rows, self._hit_row_height
        self._hit_rows = []
        if self.uid is None:
            return
        W, H = b.winfo_width(), b.winfo_height()
        if W < 50 or H < 50:
            return
        cards, used, size, _, last, _ = self.tracker.view(self.uid)
        slots = max(size or DECK_MAX, len(cards))
        row = max(self.ROW_MIN, min(self.ROW_MAX, H // slots))
        rows = list(cards.items()) + [None] * (slots - len(cards))
        if self._hover_y is not None:
            old_index, new_index = int(self._hover_y) // previous_height, int(self._hover_y) // row
            old_entry = previous_rows[old_index] if 0 <= old_index < len(previous_rows) else None
            new_entry = rows[new_index] if 0 <= new_index < len(rows) else None
            if old_entry != new_entry or self._hover_y % row >= row - 2:
                self._end_hover()
        self._hit_rows, self._hit_row_height = rows, row
        for n, entry in enumerate(rows):
            y0, y1 = n * row, (n + 1) * row - 2
            if entry is None:                                # not seen yet
                b.create_rectangle(0, y0, W - 1, y1, outline="#2c2d45", dash=(2, 2))
                b.create_text(W // 2, (y0 + y1) // 2, text="?", fill="#3c3e5c", font=self.F_CARD)
                continue
            card, skill = entry
            name, attr, ctype = self.icons.resources.card_data.get(card, (f"Card {card}", 0, 0))
            done = card in used
            job_color = readable(PLAYER_JOB_COLOR.get(CARD_TYPE_MAP.get(ctype, ""), "#9e9e9e"))
            b.create_rectangle(0, y0, W - 1, y1, fill="#191a2c" if done else "#2a2b47",
                               outline="#ffd54f" if card == last else ("#26273c" if done else "#4a4c78"),
                               width=2 if card == last else 1)
            b.create_rectangle(1, y0 + 1, 4, y1, fill="#3a3b52" if done else job_color, width=0)
            x = 8
            if attr in ATTRIBUTE_MAP:
                b.create_image(x, (y0 + y1) // 2, anchor="w", image=self.icons.attribute(attr, 14, dim=done))
                x += 17
            two_lines = row >= 28
            name_y = y0 + row // 4 + 1 if two_lines else (y0 + y1) // 2
            b.create_text(x, name_y, anchor="w", font=self.F_CARD, fill="#5d607e" if done else "#ffffff",
                          text=CardBase._fit(name, self.F_CARD, W - x - 6))
            if two_lines:
                sk = self.icons.resources.skill_names.get(skill) if skill else "（NeunWelt 充能）"
                b.create_text(x, y1 - row // 4 + 1, anchor="w", font=self.F_SKILL,
                              fill="#4a4c66" if done else "#aab0dc",
                              text=CardBase._fit(sk or f"Skill {skill}", self.F_SKILL, W - x - 6))


