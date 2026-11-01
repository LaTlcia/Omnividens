"""Single-target Agamotto damage estimate; random-region expectation occurs once."""
from __future__ import annotations

import math

from .models import DamageRange


def _number(name: str, value: float, *, positive: bool = False) -> float:
    try:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError
        number = float(value)
        if not math.isfinite(number) or number < 0 or (positive and number == 0):
            raise ValueError
    except (ValueError, OverflowError):
        requirement = "有限正数" if positive else "有限非负数"
        raise ValueError(f"{name}必须是{requirement}") from None
    return number


def estimate_damage(
    attack: float,
    defense: float,
    multiplier: float,
    crit_rate: float,
    received_multiplier: float = 1.0,
) -> DamageRange:
    """Return pre-floor expected damage and integer endpoint bounds.

    M excludes damage randomness and target Ba. Expected damage uses E[U]=.95,
    E[RandInt(1,200)]=100.5 and independent crit expectation (1+.3*p). The final
    integer floor is omitted ONLY from expected, differing by less than one
    damage point when the other supplied multipliers are fixed. Range endpoints
    include the final floor; the upper endpoint conservatively includes U=1.
    """
    attack = _number("有效攻击", attack, positive=True)
    defense = _number("有效防御", defense, positive=True)
    multiplier = _number("伤害倍率", multiplier)
    crit_rate = _number("暴击概率", crit_rate)
    received_multiplier = _number("承伤倍率", received_multiplier)
    if crit_rate > 1:
        raise ValueError("暴击概率必须在0至1之间")

    # Cap before division, including when a tiny defense would overflow A / D.
    ratio = 10 if attack >= 10 * defense else math.floor(attack / defense)
    raw_core = (attack - (2 / 3) * defense) * multiplier * (1 + .05 * ratio)
    if not math.isfinite(raw_core):
        raise ValueError("伤害核心计算结果超出有限数值范围")
    core = max(1.0, raw_core)
    expected = (core * .95 + 100.5) * (1 + .3 * crit_rate) * received_multiplier
    low_crit = 1.3 if crit_rate == 1 else 1.0
    high_crit = 1.3 if crit_rate > 0 else 1.0
    lower = (core * .9 + 1) * low_crit * received_multiplier
    upper = (core + 200) * high_crit * received_multiplier
    if not all(math.isfinite(value) for value in (expected, lower, upper)):
        raise ValueError("最终伤害计算结果超出有限数值范围")
    return DamageRange(expected=expected, minimum=math.floor(lower),
                       maximum=math.floor(upper), core=core)
