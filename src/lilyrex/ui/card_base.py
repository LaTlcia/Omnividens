"""Migrated Tk rendering; no networking or file configuration."""
from __future__ import annotations
import tkinter as tk
from .theme import *

class CardBase:
    ROW_HDR, ROW_HP, ROW_ICON = 12, 36, 47


    PAD_BOTTOM = 4


    NAME_X = 50


    BTN_W = 22


    NAME_FONT = F_NAME


    BUTTONS = (("😇", "#2e7d32", "join"), ("💀", "#c62828", "leave"),
               ("🤖", "#1565c0", "set_auto"), ("🎯", "#e08e00", "set_target"))


    SLOT_POS = [(0, c) for c in range(4)] + [(1, c) for c in range(5)] + [(2, c) for c in range(5)]


    @classmethod
    def height_for(cls, s):
        return cls.ROW_ICON + 3 * (s + ICON_GAP) + cls.PAD_BOTTOM


    @classmethod
    def min_width(cls, s):
        """Card width needed at icon edge s: 5-icon block | stacks/targets/pills | damage-heal list."""
        step = s + ICON_GAP
        middle = max(3 * step, text_width(F_SMALL, "→味方#9  敵#9") + 2,
                     text_width(F_SMALL, "AUTO") + text_width(F_SMALL, "CPU") + 24)
        hit_list = text_width(HP_LOG_FONTS[0], "-00,000,000") + text_width(F_SMALL, "00:00") + 12
        return 8 + 5 * step + 8 + middle + 4 + hit_list


    def _init_card(self, parent, bg_color, control_pool, room_provider, icons, icon_size, height):
        """State, canvas, frame, header (job/rank/name/last attribute) and the bot buttons."""
        self.bg_color = bg_color
        self.icons = icons
        self.control_pool = control_pool
        self.get_room_id = room_provider
        self.current_user = None
        self._last = None
        self._shown = False
        self._cfg, self._xy = {}, {}
        self.W = 340
        self.s = icon_size
        self.H = height

        # small width request: the column (not the card) decides the width, cards fill it
        c = self.card = tk.Canvas(parent, height=self.H, width=100, bg=CARD_BG,
                                  highlightthickness=0, bd=0)
        self.i_frame = c.create_rectangle(0, 0, 0, 0, outline=CARD_LINE, fill=CARD_BG)
        self.i_sel = c.create_rectangle(0, 0, 0, 0, outline="#ffd54f", width=2, state="hidden")   # 記牌 selection
        self.on_select = None                  # set by GameStyleGUI: called with the userId on click
        self.i_hdr = c.create_rectangle(0, 0, 0, 0, fill=CARD_HDR, width=0)
        self.i_accent = c.create_rectangle(0, 0, 0, 0, width=0)
        self.i_ct = c.create_image(8, self.ROW_HDR, anchor="w")
        self.i_rank = c.create_text(30, self.ROW_HDR, anchor="w", font=F_RANK, fill="#8a8fb3")
        self.i_name = c.create_text(self.NAME_X, self.ROW_HDR, anchor="w", font=self.NAME_FONT)
        self.i_last_attr = c.create_image(0, self.ROW_HDR, anchor="w", state="hidden")

        # per-bot control buttons (uuid == userId), drawn in the header's right corner
        self.i_btns = []
        for n, (glyph, color, action) in enumerate(self.BUTTONS):
            tag = f"btn{n}"
            enabled = getattr(control_pool, "enabled", True)
            r = c.create_rectangle(0, 0, 0, 0, fill=color if enabled else "#44445b", outline="", tags=tag)
            t = c.create_text(0, 0, text=glyph, font=F_BTN, tags=tag)
            c.tag_bind(tag, "<Button-1>", lambda e, a=action: self._emit_action(a))
            c.tag_bind(tag, "<Enter>", lambda e, r=r: (c.itemconfigure(r, outline="#ffffff"),
                                                       c.configure(cursor="hand2")))
            c.tag_bind(tag, "<Leave>", lambda e, r=r: (c.itemconfigure(r, outline=""),
                                                       c.configure(cursor="")))
            self.i_btns.append((r, t))
        c.bind("<Configure>", self._on_resize)
        c.bind("<Button-1>", self._on_click)


    def _init_mp(self):
        c = self.card
        self.i_mp_bg = c.create_rectangle(0, 0, 0, 0, fill="#15162a", outline=CARD_LINE)
        self.i_mp = c.create_rectangle(0, 0, 0, 0, fill="#4fc3f7", width=0)
        self.i_mp_ticks = [c.create_line(0, 0, 0, 0, fill="#15162a") for _ in range(3)]   # every 100, bottom edge
        self.i_mp_shadow = c.create_text(0, 0, font=F_SMALL, fill="#000000")
        self.i_mp_text = c.create_text(0, 0, font=F_SMALL, fill="#ffffff")


    def _render_header(self, user, dead, name_right):
        """Frame and header (name fitted left of `name_right`); returns the (readable) job color."""
        W, H, ic = self.W, self.H, self.icons
        job = self.icons.resources.chara_data.get(str(user['characterJobMstId']), {}).get('mainCardType', 'Unknown')
        color = readable(PLAYER_JOB_COLOR.get(job, "#9e9e9e"))
        self._coords(self.i_frame, 0, 0, W - 1, H - 1)
        self._coords(self.i_sel, 1, 1, W - 2, H - 2)
        self._coords(self.i_hdr, 1, 1, W - 1, 24)
        self._coords(self.i_accent, 0, 0, 4, H)
        self._set(self.i_accent, fill=color)
        ct = CARD_TYPE_ID.get(job)
        self._set(self.i_ct, image=ic.card_type(ct, color=color) if ct else "")
        self._set(self.i_rank, text=f"#{user.get('memberRank', '?')}")
        attr = user.get('executedCardAttribute', 0)
        name = self._fit(user['name'], self.NAME_FONT, name_right - self.NAME_X - (22 if attr in ATTRIBUTE_MAP else 4))
        self._set(self.i_name, text=name, fill="#8a8a9a" if dead else "#ffffff")
        if attr in ATTRIBUTE_MAP:
            self._coords(self.i_last_attr, self.NAME_X + text_width(self.NAME_FONT, name) + 5, self.ROW_HDR)
            self._set(self.i_last_attr, image=ic.attribute(attr), state="normal")
        else:
            self._set(self.i_last_attr, state="hidden")
        return color


    def _render_buttons(self, x0, yc):
        self.refresh_control_state()
        for n, (r, t) in enumerate(self.i_btns):
            x = x0 + n * self.BTN_W
            self._coords(r, x, yc - 9, x + self.BTN_W - 2, yc + 9)
            self._coords(t, x + (self.BTN_W - 2) / 2, yc)

    def refresh_control_state(self):
        enabled = getattr(self.control_pool, 'enabled', True)
        for (rectangle, _), (_, color, _) in zip(self.i_btns, self.BUTTONS):
            self._set(rectangle, fill=color if enabled else '#44445b')


    def _render_mp(self, m0, m1, y0, y1, mp):
        """MP bar (cap MP_MAX) in the box (m0, y0)-(m1, y1), number centered on it."""
        self._coords(self.i_mp_bg, m0, y0, m1, y1)
        self._coords(self.i_mp, m0 + 1, y0 + 1, m0 + 1 + (m1 - m0 - 2) * max(0.0, min(1.0, mp / MP_MAX)), y1)
        self._set(self.i_mp, state="normal" if mp > 0 else "hidden")
        for n, tick in enumerate(self.i_mp_ticks, 1):
            tx = m0 + (m1 - m0) * n // 4
            self._coords(tick, tx, y1 - 3, tx, y1)
        mid, yc = (m0 + m1) // 2, (y0 + y1) // 2
        self._coords(self.i_mp_shadow, mid + 1, yc + 1)
        self._coords(self.i_mp_text, mid, yc)
        self._set(self.i_mp_shadow, text=str(mp))
        self._set(self.i_mp_text, text=str(mp))


    def _render_stacks(self, x, y, user, stack_data, badge_font):
        """≤MAX_STACKS stack icons (edge self.s) from (x, y), stack count as badge."""
        step = self.s + ICON_GAP
        mine = [b for b in stack_data.get("buff", [])
                if b["userId"] == user["userId"] and b["stackType"] in STACK_ICON]
        for n, slot in enumerate(self.stack_slots):
            if n < len(mine):
                st = mine[n]
                self._draw_icon(slot, x + n * step, y, self.icons.stack(st["stackType"], self.s),
                                str(st["stackNum"] or ""), "#ffcf5c", badge_font)
            else:
                self._hide_icon(slot)


    def _render_target(self, x, y, user):
        own, enemy = user.get("ownTargetMemberRank", 0), user.get("enemyTargetMemberRank", 0)
        self._coords(self.i_target, x, y)
        self._set(self.i_target, text=f"→味方#{own or '-'}  敵#{enemy or '-'}",
                  fill="#e0e0f0" if (own or enemy) else "#6c6f93")


    def _on_click(self, event):
        if any(t.startswith("btn") for t in self.card.gettags("current")):
            return                             # bot buttons have their own handlers
        if self.on_select and self.current_user:
            self.on_select(self.current_user["userId"])


    def set_selected(self, selected):
        self._set(self.i_sel, state="normal" if selected else "hidden")
        if selected:
            self.card.tag_raise(self.i_sel)


    def _emit_action(self, payload_type):
        if not getattr(self.control_pool, "enabled", True):
            return
        u = self.current_user
        if not u:
            print("[CMD] panel has no active user yet")
            return
        if self.control_pool is None:
            print("[CMD] control pool not available")
            return
        uid = u.get("userId")
        room = self.get_room_id() if callable(self.get_room_id) else ""
        # dispatch + server response are logged by the pool / BotSession
        self.control_pool.send(uid, room, payload_type)


    def _set(self, item, **kw):
        prev = self._cfg.setdefault(item, {})
        diff = {k: v for k, v in kw.items() if k not in prev or prev[k] != v}
        if diff:
            self.card.itemconfigure(item, **diff)
            prev.update(diff)


    def _coords(self, item, *xy):
        xy = tuple(int(v) for v in xy)
        if self._xy.get(item) != xy:
            self.card.coords(item, *xy)
            self._xy[item] = xy


    def _icon_slot(self):
        c = self.card
        return (c.create_image(0, 0, anchor="nw"),
                c.create_text(0, 0, anchor="se", fill="#000000"),
                c.create_text(0, 0, anchor="se"))


    def _draw_icon(self, slot, x, y, image, label, fill, badge_font):
        """Icon at (x, y) with `label` as a corner badge."""
        img, sh, txt = slot
        s = self.s
        self._coords(img, x, y)
        self._coords(sh, x + s + 2, y + s + 3)
        self._coords(txt, x + s + 1, y + s + 2)
        self._set(img, image=image, state="normal")
        self._set(sh, text=label, font=badge_font, state="normal")
        self._set(txt, text=label, font=badge_font, fill=fill, state="normal")


    def _hide_icon(self, slot):
        for item in slot:
            self._set(item, state="hidden")


    def _pill(self, bg):
        r = self.card.create_rectangle(0, 0, 0, 0, fill=bg, outline="", state="hidden")
        t = self.card.create_text(0, 0, font=F_SMALL, fill="#ffffff", state="hidden")
        return r, t


    def _place_pill(self, pill, x, y, text, fg="#ffffff", show=True, right=False):
        """Pill with its left (or right) edge at x, centered on y; returns its width."""
        r, t = pill
        if not show:
            self._set(r, state="hidden")
            self._set(t, state="hidden")
            return 0
        w = text_width(F_SMALL, text) + 10
        if right:
            x -= w
        self._coords(r, x, y - 7, x + w, y + 7)
        self._coords(t, x + w / 2, y)
        self._set(t, text=text, fill=fg, state="normal")
        self._set(r, state="normal")
        return w


    @staticmethod
    def _fit(text, spec, max_w):
        if text_width(spec, text) <= max_w:
            return text
        while text and text_width(spec, text + "…") > max_w:
            text = text[:-1]
        return text + "…"


    def _on_resize(self, event):
        if event.width != self.W:
            self.W = event.width
            if self._last:
                self._render()


    def set_icon_size(self, s):
        if s != self.s:
            self.s = s
            self.H = self.height_for(s)
            self.card.configure(height=self.H)
            if self._last:
                self._render()


    def update(self, user, all_players, stack_data, guild_info):
        self.current_user = user
        self._last = (user, stack_data)
        self._render()
        if not self._shown:
            self.card.pack(fill=tk.X, padx=3, pady=2)
            self._shown = True


    def hide(self):
        if self._shown:
            self.card.pack_forget()
            self._shown = False


