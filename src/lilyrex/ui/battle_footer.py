"""Migrated Tk rendering; no networking or file configuration."""
from __future__ import annotations
import tkinter as tk
import time
from .theme import *

def _set_pool_label(lbl, text, fg=None):
    if getattr(lbl, '_pl_text', None) != text:
        lbl.config(text=text)
        lbl._pl_text = text
    if fg is not None and getattr(lbl, '_pl_fg', None) != fg:
        lbl.config(fg=fg)
        lbl._pl_fg = fg
    if not lbl.winfo_ismapped():
        lbl.pack(fill=tk.X, pady=1, anchor="w")


def _hide_pool_label(lbl):
    if lbl.winfo_ismapped():
        lbl.pack_forget()


class BattleFooter:
    def update_bottom_info(self, tactics_data, stack_data, neunwelt_data, now=None):

        if now is None:
            now = 0

        def _fmt_remain(epoch_ts):
            remain = max(0, min(900, epoch_ts - now))
            return time.strftime("%M:%S", time.gmtime(remain))
            
        # Orders
        pool = self.bottom_pools[0]
        n = min(len(tactics_data), 3)
        for i in range(n):
            t = tactics_data[i]
            tid = str(t['tacticsMstId'])
            name = self.resources.order_data.get(tid, {}).get('name', f"Order {tid}")
            s_time = _fmt_remain(t['startTime'])
            e_time = _fmt_remain(t['endTime'])
            txt = f"[G{t['guildDataId']}] {name}\n{s_time}~{e_time}"
            _set_pool_label(pool[i], txt, fg="#ffffff")
        for i in range(n, len(pool)):
            _hide_pool_label(pool[i])

        # Stack
        pool = self.bottom_pools[1]
        n = min(len(stack_data), 4)
        for i in range(n):
            s = stack_data[i]
            _set_pool_label(pool[i], f"Guild {s['guildDataId']}: 残り {s['effectNum']} 回", fg="#ffffff")
        for i in range(n, len(pool)):
            _hide_pool_label(pool[i])

        # neunwelt: card types as icons, redrawn only when the list changes
        pool = self.bottom_pools[2]
        neunwelt_data = neunwelt_data or {}
        cards = [c['cardType'] for c in neunwelt_data.get('cardTypeList', []) if c.get('cardType') in CARD_TYPE_MAP]
        if cards != self._nw_cards:
            self._nw_cards = cards
            cv = self.nw_canvas
            cv.delete("all")
            x = 4
            for ct in cards:
                name = CARD_TYPE_MAP[ct]
                color = readable(PLAYER_JOB_COLOR.get(name, "#9e9e9e"))
                cv.create_image(x, 2, anchor="nw", image=self.icons.card_type(ct, color=color))
                cv.create_text(x + ICON + 3, 2 + ICON // 2, anchor="w", text=name, fill=color, font=F_SMALL)
                x += ICON + 3 + text_width(F_SMALL, name) + 12
        st = neunwelt_data.get('startTime', 0)
        if st > 0:
            _set_pool_label(pool[0], f"Start: {_fmt_remain(st)}", fg="#ffffff")
        else:
            _hide_pool_label(pool[0])


