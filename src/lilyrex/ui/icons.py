"""Migrated Tk rendering; no networking or file configuration."""
from __future__ import annotations
from .theme import *

class IconBank:
    """Every PNG under assets/ as a Tk image, resized/tinted/faded once and cached."""

    def __init__(self, resources):
        self.resources = resources
        from PIL import Image, ImageTk          # pip install Pillow
        self._Image, self._ImageTk = Image, ImageTk
        self._cache = {}

    def _get(self, rel, size, dim=False, tint=None):
        key = (rel, size, dim, tint)
        img = self._cache.get(key)
        if img is None:
            Image = self._Image
            im = Image.open(self.resources.assets_path / rel).convert("RGBA")
            if im.size != (size, size):
                im = im.resize((size, size), Image.LANCZOS)
            alpha = im.getchannel("A")
            if tint:          # recolor, keeping the glyph's own shading
                gray = im.convert("L")
                peak = max((v for v, a in zip(gray.getdata(), alpha.getdata()) if a > 128), default=255) or 255
                gray = gray.point(lambda v: min(255, v * 255 // peak))
                im = Image.merge("RGB", [gray.point(lambda v, c=c: v * c // 255) for c in rgb(tint)])
                im.putalpha(alpha)
            if dim:
                im = im.convert("LA").convert("RGBA")
                im.putalpha(alpha.point(lambda v: int(v * DIM_ALPHA)))
            img = self._cache[key] = self._ImageTk.PhotoImage(im)
        return img

    def basic(self, k, level, size=ICON):
        """k: 0 ATK, 1 DEF, 2 SP.ATK, 3 SP.DEF"""
        n = k + 1 + (4 if level < 0 else 0)
        return self._get(f"Sprite/BattleIconSkillImg{n:03d}.png", size, dim=DIM_ZERO and level == 0)

    def attr_effect(self, kind, attr, level, size=ICON):
        """kind: 0 attack, 1 defense; attr: 1-5"""
        n = 18 + (attr - 1) * 4 + kind * 2 + (1 if level < 0 else 0)
        return self._get(f"Sprite/BattleIconSkillImg{n:03d}.png", size, dim=DIM_ZERO and level == 0)

    def card_type(self, card_type, color=None, size=ICON):
        return self._get(f"CardType{card_type}.png", size, tint=color)

    def stack(self, stack_type, size=ICON):
        return self._get(f"Sprite/BattleIconSkillImg{STACK_ICON[stack_type]:03d}.png", size)

    def attribute(self, attr, size=16, dim=False):
        return self._get(f"Attribute{attr}.png", size, dim=dim)


