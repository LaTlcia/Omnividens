"""Convert observed buff levels to estimated stat changes, without I/O."""
from __future__ import annotations

import math

from .models import BaseStats, BuffLevels


def _level(level: int) -> int:
    if isinstance(level, bool) or not isinstance(level, int):
        raise ValueError("buff层数必须是整数")
    return max(-20, min(20, level))


def normal_buff_ratio(level: int) -> float:
    """Return the user's piecewise base-stat percentage as a fraction."""
    value = _level(level)
    if value < -10:
        return -0.50 + 0.02 * (value + 10)
    return 0.05 * value


def elemental_buff_ratio(level: int) -> float:
    """Elemental attack/defense uses 2.5% of the matching base-stat mean."""
    return 0.025 * _level(level)


def _validate(stats: BaseStats, attack_type: str, attribute: int) -> None:
    if attack_type not in ("physical", "magical"):
        raise ValueError("attack_type必须是physical或magical")
    if isinstance(attribute, bool) or attribute not in (1, 2, 3, 4, 5):
        raise ValueError("属性必须是1至5")
    for name in ("atk", "sp_atk", "defense", "sp_defense"):
        value = getattr(stats, name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"基础面板{name}必须是数值")
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"基础面板{name}必须是有限非负数")


def effective_attack(
    stats: BaseStats, buffs: BuffLevels, attack_type: str, attribute: int
) -> float:
    """Base attack with ordinary buff, plus elemental increment from base mean."""
    _validate(stats, attack_type, attribute)
    base = stats.atk if attack_type == "physical" else stats.sp_atk
    level = buffs.atk if attack_type == "physical" else buffs.sp_atk
    elemental = buffs.elemental_attack.get(attribute, 0)
    value = base * (1 + normal_buff_ratio(level))
    value += (stats.atk / 2 + stats.sp_atk / 2) * elemental_buff_ratio(elemental)
    if not math.isfinite(value):
        raise ValueError("有效攻击计算结果超出有限数值范围")
    return max(1.0, value)


def effective_defense(
    stats: BaseStats, buffs: BuffLevels, attack_type: str, attribute: int
) -> float:
    """Elemental defense uses the mean of base DEF and base Sp.DEF."""
    _validate(stats, attack_type, attribute)
    base = stats.defense if attack_type == "physical" else stats.sp_defense
    level = buffs.defense if attack_type == "physical" else buffs.sp_defense
    elemental = buffs.elemental_defense.get(attribute, 0)
    value = base * (1 + normal_buff_ratio(level))
    value += (stats.defense / 2 + stats.sp_defense / 2) * elemental_buff_ratio(elemental)
    if not math.isfinite(value):
        raise ValueError("有效防御计算结果超出有限数值范围")
    return max(1.0, value)
