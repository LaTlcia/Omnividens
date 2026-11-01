"""Migrated Tk rendering; no networking or file configuration."""
from __future__ import annotations
import tkinter as tk
from .theme import *
from .deck_console import DeckConsole
from .front_card import PlayerCardPanel
from .playback_controls import PlaybackControls

class WindowLayout:
    def setup_ui(self):
        # 控制台: full-height sidebar on the right; controls get added to self.console later
        side = tk.Frame(self.root, bg="#16213e", width=CONSOLE_COL_W, relief=tk.RIDGE, bd=1)
        side.pack(side=tk.RIGHT, fill=tk.Y)
        side.pack_propagate(False)
        tk.Label(side, text="控制台", fg="white", bg="#16213e", font=("Arial", 11, "bold")).pack(fill=tk.X, pady=(6, 2))
        self.console = tk.Frame(side, bg="#16213e")
        self.console.pack(fill=tk.BOTH, expand=True)
        self.deck_console = DeckConsole(self.console, self.icons)
        # everything else (top bar, battlefield, bottom bar) lives left of it
        self.main = tk.Frame(self.root, bg="#1a1a2e")
        self.main.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.top_frame = tk.Frame(self.main, bg="#16213e", height=132)
        self.top_frame.pack(fill=tk.X, pady=(0, 3))
        self.top_frame.pack_propagate(False)

        row1 = tk.Frame(self.top_frame, bg="#16213e")
        row1.pack(fill=tk.X, pady=3)

        self.lbl_guild_left = tk.Label(row1, text="Guild A", font=("Arial", 13, "bold"), fg="#00d4ff", bg="#16213e")
        self.lbl_guild_left.pack(side=tk.LEFT, padx=20)

        self.lbl_cmd_status = tk.Label(row1, text="BOTS: …",
                                       font=("Arial", 9, "bold"), fg="#888888", bg="#16213e")
        self.lbl_cmd_status.pack(side=tk.LEFT, padx=10)

        center = tk.Frame(row1, bg="#16213e")
        center.pack(side=tk.LEFT, expand=True)
        self.playback_controls = PlaybackControls(center, self.playback)
        self.lbl_countdown = self.playback_controls.countdown
        self.btn_seek = self.playback_controls.btn_seek
        self.btn_live = self.playback_controls.btn_live

        self.btn_swap = tk.Button(center, text="Swap View", command=self.swap_view, bg="#ffdd00")
        self.btn_swap.pack()

        score_f = tk.Frame(center, bg="#16213e")
        score_f.pack()
        self.lbl_score_left = tk.Label(score_f, text="0", font=("Arial", 16), fg="#00d4ff", bg="#16213e")
        self.lbl_score_left.pack(side=tk.LEFT)
        tk.Label(score_f, text=" VS ", fg="white", bg="#16213e").pack(side=tk.LEFT)
        self.lbl_score_right = tk.Label(score_f, text="0", font=("Arial", 16), fg="#ff6b9d", bg="#16213e")
        self.lbl_score_right.pack(side=tk.LEFT)

        self.lbl_guild_right = tk.Label(row1, text="Guild B", font=("Arial", 13, "bold"), fg="#ff6b9d", bg="#16213e")
        self.lbl_guild_right.pack(side=tk.RIGHT, padx=20)

        wr_frame = tk.Frame(self.top_frame, bg="#16213e")
        wr_frame.pack(fill=tk.X)
        self.lbl_wr_a = tk.Label(wr_frame, text="WR-A: -", fg="white", bg="#16213e")
        self.lbl_wr_a.pack(side=tk.LEFT, expand=True)
        self.lbl_wr_b = tk.Label(wr_frame, text="WR-B: -", fg="white", bg="#16213e")
        self.lbl_wr_b.pack(side=tk.LEFT, expand=True)

        self.battlefield = tk.Frame(self.main, bg="#1a1a2e")
        self.battlefield.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.cols = []
        col_confs = [("L-Rear", "#0f3460", 0), ("L-Front", "#1a5490", 1), ("R-Front", "#6b2d5c", 2), ("R-Rear", "#533483", 3)]

        for t, c, i in col_confs:
            f = tk.Frame(self.battlefield, bg=c, relief=tk.RIDGE, bd=1)
            f.grid(row=0, column=i, sticky="nsew", padx=2)
            if i in (0, 3):     # 後衛: fixed narrow column of compact cards
                self.battlefield.grid_columnconfigure(i, weight=0, minsize=REAR_COL_W)
            else:
                self.battlefield.grid_columnconfigure(i, weight=1, uniform="front")
            tk.Label(f, text=t, fg="white", bg=c).pack(fill=tk.X)
            cf = tk.Frame(f, bg=c)
            cf.pack(fill=tk.BOTH, expand=True)
            self.cols.append({'frame': cf, 'color': c, 'panels': []})
        self.cols[1]['frame'].bind("<Configure>", lambda e: self._fit_icon_size())

        self.battlefield.grid_rowconfigure(0, weight=1)

        self.bottom_frame = tk.Frame(self.main, bg="#16213e", height=100)
        self.bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(5, 0), before=self.battlefield)
        self.bottom_frame.pack_propagate(False)

        self.bottom_frame.grid_columnconfigure(0, weight=1)
        self.bottom_frame.grid_columnconfigure(1, weight=1)
        self.bottom_frame.grid_columnconfigure(2, weight=1)
        self.bottom_frame.grid_rowconfigure(0, weight=1)

        self.bottom_sections = []
        titles = ["🎯 Orders", "📊 Stack", "🌟 Ballgame"]

        for i, title in enumerate(titles):
            f = tk.Frame(self.bottom_frame, bg="#0f3460", relief=tk.RIDGE, bd=2)
            f.grid(row=0, column=i, sticky="nsew", padx=5, pady=5)
            tk.Label(f, text=title, fg="#00d4ff", bg="#0f3460", font=("Arial", 10, "bold")).pack(fill=tk.X, pady=2)
            content = tk.Frame(f, bg="#0f3460")
            content.pack(fill=tk.BOTH, expand=True, padx=2)
            self.bottom_sections.append(content)

        pool_sizes = [3, 4, 1]
        self.bottom_pools = []
        for idx, content in enumerate(self.bottom_sections):
            pool = []
            for _ in range(pool_sizes[idx]):
                lbl = tk.Label(content, text="", fg="white", bg="#0f3460",
                               justify=tk.LEFT, anchor="w", font=("Arial", 9),
                               wraplength=300)
                pool.append(lbl)
            self.bottom_pools.append(pool)

        self.nw_canvas = tk.Canvas(self.bottom_sections[2], height=ICON + 4, bg="#0f3460",
                                   highlightthickness=0)
        self.nw_canvas.pack(fill=tk.X)
        self._nw_cards = None


    def _fit_icon_size(self):
        """Largest buff/debuff icon edge that still fits `_max_rows` cards in a column."""
        cf = self.cols[1]['frame']               # a 前衛 column
        h, w = cf.winfo_height(), cf.winfo_width()
        if h < 100:
            return                              # not laid out yet
        per_card = h / self._max_rows - 4       # card pady=2
        s = int((per_card - PlayerCardPanel.height_for(0)) / 3)   # height_for(s) = height_for(0) + 3s
        s = max(ICON_MIN, min(ICON_MAX, s))
        while s > ICON_MIN and PlayerCardPanel.min_width(s) > w - 6:   # card padx=3
            s -= 1
        if s != self.icon_size:
            self.icon_size = s
            for col in self.cols:
                for panel in col['panels']:
                    panel.set_icon_size(s)


