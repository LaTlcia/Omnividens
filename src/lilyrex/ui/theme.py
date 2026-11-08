"""Migrated Tk rendering; no networking or file configuration."""
from __future__ import annotations
from tkinter import font
from lilyrex.domain.battle_time import BATTLE_SECONDS

STACK_TYPE_MAP = {1: "増傷", 2: "増効", 3: "増療", 4: "減傷"}
CARD_TYPE_MAP = {1: "通常単体", 2: "通常範囲", 3: "特殊単体", 4: "特殊範囲", 5: "支援", 6: "妨害", 7: "回復"}
ATTRIBUTE_MAP = {1: "火", 2: "水", 3: "風", 4: "光", 5: "闇"}
ATTR_COLORS = {1: "#FF4444", 2: "#4444FF", 3: "#44FF44", 4: "#FFFF44", 5: "#AA44FF"}
# Deck stripe colors (available, used), keyed by the observed skill's card type.
DECK_STRIPE_COLORS = {
    **dict.fromkeys((1, 2, 3, 4), ("#c0c0c0", "#62626b")),
    5: ("#ff6060", "#874046"),
    6: ("#599fff", "#355784"),
    7: ("#6bcf7f", "#406f4b"),
}
PLAYER_JOB_COLOR = {
    "通常単体": "#FF6B6B", "通常範囲": "#FF8E53",
    "特殊単体": "#FFA94D", "特殊範囲": "#FFD93D",
    "支援": "#AD1457", "妨害": "#1F1E33", "回復": "#6BCF7F"
}

EFFECT_DAMAGE, EFFECT_HEAL = 1, 2
ICON = 20                     # default icon edge (px); also NeunWelt bar
ICON_MIN, ICON_MAX = 14, 30   # buff/debuff block scales within this to fit the column (source art is 30px)
ICON_GAP = 2
DIM_ZERO = True               # level 0 → faded icon, so real buffs/debuffs stand out
DIM_ALPHA = 0.3
# Per-icon level changes: bright fill, outline, dim fill; milliseconds of UI time.
BUFF_FLASH_UP = ("#ff7070", "#ff9b9b", "#873b49")
BUFF_FLASH_DOWN = ("#69b9ff", "#9ed3ff", "#315980")
BUFF_FLASH_DIM_MS, BUFF_FLASH_END_MS = 250, 800
BASIC_EFFECT_FIELDS = ("physicalAttackEffectLevel", "physicalDefenseEffectLevel",
                       "magicalAttackEffectLevel", "magicalDefenseEffectLevel")
CARD_TYPE_ID = {v: k for k, v in CARD_TYPE_MAP.items()}
STACK_ICON = {1: 51, 2: 57, 3: 55, 4: 54}   # stackType (STACK_TYPE_MAP) → BattleIconSkillImg0xx
MAX_STACKS = 3                              # at most 3 stack kinds per player in battle
MP_MAX = 400
REAR_COL_W = 180                            # 後衛 columns (compact cards); 前衛 columns share the rest
CONSOLE_COL_W = 250                         # 控制台 sidebar, full window height on the right
HP_LOG_LEN = 4                              # recent damage/heal entries listed per player
# per effectType: sign, list colors newest → oldest, flash/pop color
HP_STYLE = {EFFECT_DAMAGE: ("-", ("#ff5c5c", "#e07878", "#b87c86", "#8c7690"), "#ff4d4d"),
            EFFECT_HEAL: ("+", ("#5ce07a", "#72c98a", "#7aa88c", "#728a86"), "#3ddc84")}
HP_LOG_FONTS = (("Arial", 9, "bold"), ("Arial", 8, "bold"), ("Arial", 8, "bold"), ("Arial", 8, "bold"))
HP_TIME_COLOR = "#8a8fb3"
# pop: (ms after the hit, font size, y offset) — jumps up big, then settles into the list
HIT_POP_FRAMES = ((0, 12, 2), (35, 18, -4), (70, 23, -9), (120, 22, -8), (180, 20, -6),
                  (520, 20, -6), (610, 15, -2), (680, 11, 0))
HIT_POP_END = 740
CARD_BG, CARD_HDR, CARD_LINE = "#23243a", "#2d2e4a", "#3a3b5c"
F_NAME = ("Arial", 11, "bold")
F_RANK = ("Arial", 9, "bold")
F_SMALL = ("Arial", 8, "bold")
F_BTN = ("Arial", 10)



def rgb(hex_color):
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def readable(hex_color, min_lum=0.42):
    """Lighten a job color until it shows up on the dark card background."""
    r, g, b = rgb(hex_color)
    while (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 < min_lum:
        r, g, b = (c + (255 - c) // 4 for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def hp_color(ratio):
    return "#3ddc84" if ratio > 0.5 else "#f5c542" if ratio > 0.25 else "#ff5252"



_TEXT_FONTS, _TEXT_W = {}, {}
def text_width(spec, text):
    key = (spec, text)
    w = _TEXT_W.get(key)
    if w is None:
        f = _TEXT_FONTS.get(spec) or _TEXT_FONTS.setdefault(spec, font.Font(font=spec))
        w = _TEXT_W[key] = f.measure(text)
    return w


