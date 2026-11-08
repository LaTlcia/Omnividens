"""Migrated Tk rendering; no networking or file configuration."""
from __future__ import annotations
from collections.abc import Mapping
from types import MappingProxyType
import tkinter as tk
from .theme import *
from .card_base import CardBase
from .playback_controls import DarkButton
from lilyrex.domain.card_ranking import CardDamageRank, order_ranked_cards
from lilyrex.domain.deck_tracker import DECK_MAX

class DeckConsole:
    """控制台 記牌 view of one player: a box per memoria (card name + last skill used),
    bright = still to come this cycle, dim = used, gold edge = the latest one."""
    ROW_MIN, ROW_MAX = 24, 34
    BG = "#16213e"
    F_CARD = ("Arial", 9, "bold")
    F_SKILL = ("Arial", 8)
    F_HEAD = ("Arial", 11, "bold")
    F_RANK = ("Arial", 7, "bold")
    METRIC_GAP = 6
    LETHAL_COLOR, LETHAL_DIM = "#d5d8e8", "#9597ab"
    AVG_COLOR, MAX_COLOR = "#55c9ff", "#ff707d"
    AVG_DIM, MAX_DIM = "#3e6983", "#805060"

    def __init__(self, parent, icons, *, resolve_card_type, sort_parent=None):
        self.resolve_card_type = resolve_card_type
        self.icons = icons
        self.uid = self.user = self.tracker = None
        self._head_key = object()
        self._lethal_columns: tuple[int, int] | None = None
        self.on_hover = None
        self.on_hover_end = None
        self.on_hover_leave = None
        self._hit_rows = []
        self._hit_row_height = self.ROW_MIN
        self._hover_y = None
        self.rankings: Mapping[int, CardDamageRank] = MappingProxyType({})
        self.sort_mode: str | None = None
        self.sort_controls = tk.Frame(sort_parent or parent, bg=self.BG)
        self.sort_controls.pack(side=tk.RIGHT if sort_parent is not None else tk.TOP,
                                anchor="e", padx=(2, 6))
        self.btn_sort_avg = DarkButton(self.sort_controls, "A↓", lambda: self.toggle_sort("avg"))
        self.btn_sort_max = DarkButton(self.sort_controls, "M↓", lambda: self.toggle_sort("max"))
        for button, color in ((self.btn_sort_avg, self.AVG_COLOR), (self.btn_sort_max, self.MAX_COLOR)):
            button.config(fg=color, font=("Arial", 9, "bold"), padx=4, pady=1,
                          highlightcolor=color)
            button.pack(side=tk.LEFT, padx=(2, 0))
            button.set_enabled(False)
        self.head = tk.Canvas(parent, height=50, bg=self.BG, highlightthickness=0)
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
            self._end_hover(leaving=True)
            return
        if self.on_hover:
            card, skill = self._hit_rows[index]
            self.on_hover(self.uid, card, skill, event.x_root, event.y_root)

    def show(self, uid, user, tracker):
        self._end_hover()
        self.uid, self.user, self.tracker = uid, user, tracker
        self._head_key = object()
        self.rankings = MappingProxyType({})
        self.redraw()

    def set_rankings(self, rankings: Mapping[int, CardDamageRank]) -> None:
        """Render a complete result batch without retaining a mutable caller mapping."""
        self.rankings = MappingProxyType(dict(rankings))
        self.redraw()

    def toggle_sort(self, metric: str) -> None:
        """Descending AVG/MAX, or original tracker order when clicked again."""
        if metric not in ("avg", "max"):
            raise ValueError("排序指标必须为avg或max")
        if not self._has_ranked_cards():
            return
        self._end_hover()
        self.sort_mode = None if self.sort_mode == metric else metric
        self.redraw()

    def _has_ranked_cards(self) -> bool:
        if self.uid is None or self.tracker is None:
            return False
        cards = self.tracker.view(self.uid)[0]
        return any(entry.card_id == card and entry.skill_id == skill and entry.reason is None
                   and entry.avg_rank is not None and entry.max_rank is not None
                   for card, skill in cards.items()
                   if (entry := self.rankings.get(card)) is not None)

    def _update_sort_buttons(self) -> None:
        enabled = self._has_ranked_cards()
        for metric, button, color in (("avg", self.btn_sort_avg, self.AVG_COLOR),
                                      ("max", self.btn_sort_max, self.MAX_COLOR)):
            button.set_enabled(enabled)
            selected = self.sort_mode == metric
            button.config(relief=tk.SUNKEN if selected else tk.FLAT,
                          highlightbackground=color if selected else "#3a3b5c")

    def _rank_for(self, card: int, skill: int, card_type: int) -> CardDamageRank | None:
        entry = self.rankings.get(card)
        if entry is None or (entry.card_id, entry.skill_id) != (card, skill):
            return None
        if card_type not in (1, 2, 3, 4) and entry.avg_rank is None and entry.max_rank is None:
            return None
        return entry

    def set_user(self, user):
        """Latest frame's data for the shown player (name/rank/job may change)."""
        self.user = user
        self._draw_head()

    def redraw(self):
        self._update_sort_buttons()
        self._lethal_columns = self._draw_body()
        self._draw_head()

    def _draw_head(self):
        h, u = self.head, self.user
        if self.uid is None:
            key = None
        else:
            cards, used, size, cycle, _, clean = self.tracker.view(self.uid)
            job = self.icons.resources.chara_data.get(str((u or {}).get('characterJobMstId')), {}).get('mainCardType', '')
            key = ((u or {}).get('name'), (u or {}).get('memberRank'), job, len(cards), len(used), size, cycle, clean)
        W = max(h.winfo_width(), 200)
        cache_key = (key, W, self._lethal_columns)
        if cache_key == self._head_key:
            return
        self._head_key = cache_key
        h.delete("all")
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
            info = (f"第{cycle or '?'}轮   已用 {n_used}/{total}", f"剩 {total - n_used}   已见 {n_cards}")
        else:                              # joined mid-cycle: still working out where cycles break
            info = ("中途加入·推算轮次中", f"已用≥{n_used}   已见 {n_cards}")
        full_info = "   ".join(info)
        info_width = W - 8
        header_y = (29, 42)
        if self._lethal_columns is not None:
            for index in range(4):
                h.create_text(self._lethal_columns[index % 2], header_y[index // 2],
                              anchor="e", font=self.F_RANK, fill=self.LETHAL_COLOR,
                              text=f"#{index + 1}", tags=f"lethal_header_{index + 1}")
            info_width = self._lethal_columns[0] - text_width(self.F_RANK, "#1") - self.METRIC_GAP - 2
        if text_width(F_SMALL, full_info) <= info_width:
            h.create_text(2, 35, anchor="w", font=F_SMALL, fill="#aab0dc",
                          text=full_info, tags="deck_info")
        else:
            for y, part in zip(header_y, info):
                h.create_text(2, y, anchor="w", font=F_SMALL, fill="#aab0dc",
                              text=CardBase._fit(part, F_SMALL, info_width), tags="deck_info")

    def _draw_body(self) -> tuple[int, int] | None:
        b = self.body
        b.delete("all")
        previous_rows, previous_height = self._hit_rows, self._hit_row_height
        self._hit_rows = []
        if self.uid is None:
            return None
        W, H = b.winfo_width(), b.winfo_height()
        if W < 50 or H < 50:
            return None
        cards, used, size, _, last, _ = self.tracker.view(self.uid)
        slots = max(size or DECK_MAX, len(cards))
        row = max(self.ROW_MIN, min(self.ROW_MAX, H // slots))
        rows = list(order_ranked_cards(tuple(cards.items()), self.rankings, self.sort_mode))
        rows += [None] * (slots - len(cards))
        if self._hover_y is not None:
            old_index, new_index = int(self._hover_y) // previous_height, int(self._hover_y) // row
            old_entry = previous_rows[old_index] if 0 <= old_index < len(previous_rows) else None
            new_entry = rows[new_index] if 0 <= new_index < len(rows) else None
            if old_entry != new_entry or self._hover_y % row >= row - 2:
                self._end_hover()
        self._hit_rows, self._hit_row_height = rows, row
        # Share column edges across the deck. Arial uses equal-width digits.
        largest_percent = max((value for ranked in self.rankings.values()
                               for value in ranked.lethal_percentages if value is not None),
                              default=0)
        percent_width = text_width(self.F_RANK, f"{max(999, largest_percent)}%") + self.METRIC_GAP
        rank_width = text_width(self.F_RANK, f"#{slots}") + self.METRIC_GAP
        rank_right = W - 6
        percent_right = rank_right - rank_width
        columns = (percent_right - percent_width, percent_right)
        has_grid = False
        for n, entry in enumerate(rows):
            y0, y1 = n * row, (n + 1) * row - 2
            if entry is None:                                # not seen yet
                b.create_rectangle(0, y0, W - 1, y1, outline="#2c2d45", dash=(2, 2))
                b.create_text(W // 2, (y0 + y1) // 2, text="?", fill="#3c3e5c", font=self.F_CARD)
                continue
            card, skill = entry
            name, attr, _ = self.icons.resources.card_data.get(card, (f"Card {card}", 0, 0))
            ctype = self.resolve_card_type(card, skill) or 0
            done = card in used
            b.create_rectangle(0, y0, W - 1, y1, fill="#191a2c" if done else "#2a2b47",
                               outline="#ffd54f" if card == last else ("#26273c" if done else "#4a4c78"),
                               width=2 if card == last else 1)
            if colors := DECK_STRIPE_COLORS.get(ctype):
                available_color, used_color = colors
                b.create_rectangle(1, y0 + 1, 4, y1, fill=used_color if done else available_color,
                                   width=0, tags=f"card_stripe_{card}")
            x = 8
            if attr in ATTRIBUTE_MAP:
                b.create_image(x, (y0 + y1) // 2, anchor="w", image=self.icons.attribute(attr, 14, dim=done))
                x += 17
            ranking = self._rank_for(card, skill, ctype)
            label_width = percent_right - 2 * percent_width - x if ranking is not None else rank_right - x
            two_lines = row >= 28
            name_y = y0 + row // 4 + 1 if two_lines else (y0 + y1) // 2
            b.create_text(x, name_y, anchor="w", font=self.F_CARD, fill="#5d607e" if done else "#ffffff",
                          text=CardBase._fit(name, self.F_CARD, label_width), tags=f"card_name_{card}")
            if two_lines:
                sk = self.icons.resources.skill_names.get(skill) if skill else "（NeunWelt 充能）"
                b.create_text(x, y1 - row // 4 + 1, anchor="w", font=self.F_SKILL,
                              fill="#4a4c66" if done else "#aab0dc",
                              text=CardBase._fit(sk or f"Skill {skill}", self.F_SKILL, label_width))
            if ranking is not None:
                has_grid = True
                for index, value in enumerate(ranking.lethal_percentages):
                    cell_y = y0 + (row // 4 if index < 2 else 3 * row // 4)
                    b.create_text(columns[index % 2], cell_y, anchor="e", font=self.F_RANK,
                                  text="—" if value is None else f"{value}%",
                                  fill=self.LETHAL_DIM if done else self.LETHAL_COLOR,
                                  tags=f"lethal_{index + 1}_{card}")
                for metric, rank, offset, color in (
                        ("avg", ranking.avg_rank, row // 4, self.AVG_DIM if done else self.AVG_COLOR),
                        ("max", ranking.max_rank, 3 * row // 4, self.MAX_DIM if done else self.MAX_COLOR)):
                    b.create_text(rank_right, y0 + offset, anchor="e", font=self.F_RANK,
                                  text=f"#{rank}" if rank is not None else "—", fill=color,
                                  tags=f"rank_{metric}_{card}")
        return columns if has_grid else None


