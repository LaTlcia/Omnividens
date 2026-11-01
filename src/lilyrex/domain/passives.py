"""Expected passive contribution. Legendary effects do not roll activation."""
from __future__ import annotations
import math
from .models import DamageSkill
from .passive_models import CardPassives, DeckCard, PassiveEstimate, PassivePoolSettings


def activation_probability(base: float, theme: bool, rate_up: float, rate_down: float) -> float:
    if any(not math.isfinite(x) or x < 0 for x in (base, rate_up, rate_down)) or base > 1:
        raise ValueError("被动发动率参数无效")
    return min(1.0, max(0.0, (base + (.02 if theme else 0)) * (1 + rate_up) * (1 - rate_down)))


def estimate_passives(skill: DamageSkill, pairs: tuple[tuple[DeckCard, CardPassives], ...],
                      settings: PassivePoolSettings, rate_up: float, rate_down: float) -> PassiveEstimate:
    up = crit = 0.0
    notes: list[str] = []
    for card, definition in pairs:
        level = settings.level_multiplier if card.passive_level_multiplier is None else card.passive_level_multiplier
        if not math.isfinite(level) or level <= 0:
            raise ValueError("被动等级倍率无效")
        for entry in definition.entries:
            if entry.kind != 'damage':
                continue
            p = activation_probability(entry.base_probability, entry.host_attribute in settings.theme_attributes,
                                       rate_up, rate_down)
            up += entry.coefficient * level * p
        if definition.legendary:
            ll = settings.legendary_level if card.legendary_level is None else card.legendary_level
            if ll == 0:
                notes.append("Legendary等级未知，未计入")
            elif not 1 <= ll <= len(definition.legendary):
                raise ValueError("Legendary等级超出主数据范围")
            else:
                for entry in definition.legendary[ll-1]:
                    if entry.attribute == skill.attribute and entry.attack_type == skill.attack_type:
                        up += entry.up
                        crit += entry.crit
    notes.insert(0, f"被动池UP期望+{up:.1%}（被动等级倍率默认×{settings.level_multiplier:g}）")
    return PassiveEstimate(up, crit, tuple(dict.fromkeys(notes)))
