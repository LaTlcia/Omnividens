"""Migrated Tk rendering; no networking or file configuration."""
from __future__ import annotations
from .theme import *
from .card_base import CardBase

class PlayerCardPanel(CardBase):
    def __init__(self, parent, bg_color, control_pool=None, room_provider=None, icons=None, icon_size=ICON,
                 hp_log=None):
        self._init_card(parent, bg_color, control_pool, room_provider, icons, icon_size, self.height_for(icon_size))
        c = self.card
        self.hp_log = hp_log if hp_log is not None else {}   # userId -> [(effectType, value, clock)], newest first
        self._pop_jobs = []
        self._popping = False

        self.i_hp_bg = c.create_rectangle(0, 0, 0, 0, fill="#15162a", outline=CARD_LINE)
        self.i_hp = c.create_rectangle(0, 0, 0, 0, width=0)
        self.i_hp_shadow = c.create_text(0, 0, font=F_SMALL, fill="#000000")
        self.i_hp_text = c.create_text(0, 0, font=F_SMALL)
        self._init_mp()
        self.i_rcv = self._pill("#00838f")

        # icon slots (image, badge shadow, badge); positioned in _render from self.s
        self.slots = [self._icon_slot() for _ in self.SLOT_POS]
        self.stack_slots = [self._icon_slot() for _ in range(MAX_STACKS)]
        self.i_target = c.create_text(0, 0, anchor="w", font=F_SMALL)
        self.i_auto = self._pill("#1565c0")
        self.i_cpu = self._pill("#616161")
        self.i_log_val = [c.create_text(0, 0, anchor="e", font=f) for f in HP_LOG_FONTS]
        self.i_log_time = [c.create_text(0, 0, anchor="e", font=F_SMALL, fill=HP_TIME_COLOR)
                           for _ in HP_LOG_FONTS]
        # damage pop, created last so it draws over everything
        self.i_pop_shadow = c.create_text(0, 0, anchor="e", fill="#000000", state="hidden")
        self.i_pop = c.create_text(0, 0, anchor="e", fill="#ff4d4d", state="hidden")


    def _render(self):
        user, stack_data = self._last
        W, s, ic = self.W, self.s, self.icons
        hp = user['hp']
        max_hp = (user.get('maxHp') or hp or 1) + user.get('maxHpEffect', 0)   # HP-up buffs raise the cap
        dead = hp <= 0
        btn_x = W - 4 - len(self.BUTTONS) * self.BTN_W
        self._render_header(user, dead, btn_x)
        self._render_buttons(btn_x, self.ROW_HDR)

        # HP / MP / 回復
        x0, x1, y0, y1 = 8, W - 110, self.ROW_HP - 7, self.ROW_HP + 7
        ratio = max(0.0, min(1.0, hp / max_hp))
        self._coords(self.i_hp_bg, x0, y0, x1, y1)
        self._coords(self.i_hp, x0 + 1, y0 + 1, x0 + 1 + (x1 - x0 - 2) * ratio, y1)
        self._set(self.i_hp, fill=hp_color(ratio), state="hidden" if dead else "normal")
        txt = "DOWN" if dead else f"{hp:,} / {max_hp:,}"
        mid = (x0 + x1) // 2
        self._coords(self.i_hp_shadow, mid + 1, self.ROW_HP + 1)
        self._coords(self.i_hp_text, mid, self.ROW_HP)
        self._set(self.i_hp_shadow, text=txt)
        self._set(self.i_hp_text, text=txt, fill="#ff5252" if dead else "#ffffff")
        self._render_mp(x1 + 6, W - 46, y0 + 2, y1 - 2, user['sp'])
        self._place_pill(self.i_rcv, W - 5, self.ROW_HP, "回復", show=user.get('isSpRecoveryMode'), right=True)

        # 3x5 buff/debuff block, level as corner badge
        atk = {e["attribute"]: e["effectLevel"] for e in user.get("attributeAttackEffectLevel", [])}
        dfn = {e["attribute"]: e["effectLevel"] for e in user.get("attributeDefenseEffectLevel", [])}
        specs = [(ic.basic(k, user.get(f, 0), s), user.get(f, 0)) for k, f in enumerate(BASIC_EFFECT_FIELDS)]
        specs += [(ic.attr_effect(0, a, atk.get(a, 0), s), atk.get(a, 0)) for a in ATTRIBUTE_MAP]
        specs += [(ic.attr_effect(1, a, dfn.get(a, 0), s), dfn.get(a, 0)) for a in ATTRIBUTE_MAP]
        badge_font = ("Arial", max(8, s * 2 // 5), "bold")
        step = s + ICON_GAP
        for slot, (row, col), (image, lv) in zip(self.slots, self.SLOT_POS, specs):
            self._draw_icon(slot, 8 + col * step, self.ROW_ICON + row * step, image,
                            str(abs(lv)) if lv else "", "#ffcf5c" if lv > 0 else "#7cc4ff", badge_font)

        # right of the block, one line per icon row: stacks / targets / AUTO CPU
        rx = 8 + 5 * step + 8
        row_y = [self.ROW_ICON + r * step + s // 2 for r in range(3)]
        self._render_stacks(rx, self.ROW_ICON, user, stack_data, badge_font)
        self._render_target(rx + 2, row_y[1], user)
        x = rx
        x += self._place_pill(self.i_auto, x, row_y[2], "AUTO", show=user.get("isAuto"))
        if x > rx:
            x += 4
        self._place_pill(self.i_cpu, x, row_y[2], "CPU", show=user.get("isCpu"))

        # recent damage/heal, newest on top: battle clock | -dmg / +heal
        log = self.hp_log.get(user["userId"], ())
        time_x = W - 6 - text_width(HP_LOG_FONTS[0], "-00,000,000") - 6
        for n, (val_item, time_item) in enumerate(zip(self.i_log_val, self.i_log_time)):
            if n < len(log) and not (n == 0 and self._popping):   # the pop stands in for the newest
                kind, value, clock = log[n]
                sign, colors, _ = HP_STYLE[kind]
                y = self._log_row_y(n)
                self._coords(val_item, W - 6, y)
                self._coords(time_item, time_x, y)
                self._set(val_item, text=f"{sign}{value:,}", fill=colors[n], state="normal")
                self._set(time_item, text=clock, state="normal")
            else:
                self._set(val_item, state="hidden")
                self._set(time_item, state="hidden")


    def _log_row_y(self, n):
        line_h = 3 * (self.s + ICON_GAP) / HP_LOG_LEN
        return self.ROW_ICON + line_h * n + line_h / 2

    def cancel_hp_animation(self):
        """Discard callbacks and visuals belonging to a different viewing time."""
        for job in self._pop_jobs:
            self.card.after_cancel(job)
        self._pop_jobs.clear()
        self._popping = False
        self.card.itemconfigure(self.i_pop, state='hidden')
        self.card.itemconfigure(self.i_pop_shadow, state='hidden')
        self.card.itemconfigure(self.i_frame, outline=CARD_LINE, width=1)


    def pop_hp(self, kind, value):
        """Called after hp_log got this entry: refresh the list, flash the frame, pop the number."""
        if not self._last:
            return
        self._popping = True
        self._render()
        c = self.card
        for job in self._pop_jobs:
            c.after_cancel(job)
        sign, _, color = HP_STYLE[kind]
        text = f"{sign}{value:,}"
        x, y0 = self.W - 6, self._log_row_y(0)
        c.itemconfigure(self.i_pop, text=text, fill=color, state="normal")
        c.itemconfigure(self.i_pop_shadow, text=text, state="normal")
        c.itemconfigure(self.i_frame, outline=color, width=2)

        def frame(size, dy):
            f = ("Arial", size, "bold")
            c.itemconfigure(self.i_pop, font=f)
            c.itemconfigure(self.i_pop_shadow, font=f)
            c.coords(self.i_pop, x, y0 + dy)
            c.coords(self.i_pop_shadow, x + 2, y0 + dy + 2)

        def end():
            c.itemconfigure(self.i_pop, state="hidden")
            c.itemconfigure(self.i_pop_shadow, state="hidden")
            self._popping = False
            self._render()

        def unflash():
            c.itemconfigure(self.i_frame, outline=CARD_LINE, width=1)

        frame(*HIT_POP_FRAMES[0][1:])
        self._pop_jobs = [c.after(t, frame, size, dy) for t, size, dy in HIT_POP_FRAMES[1:]]
        self._pop_jobs += [c.after(HIT_POP_END, end), c.after(350, unflash)]


