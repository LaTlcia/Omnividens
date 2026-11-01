"""Resolve observed previous-card conditions without inventing hidden history."""
from __future__ import annotations

from dataclasses import dataclass
import math

from .models import DamageSkill


@dataclass(frozen=True)
class ElementCondition:
    multiplier: float
    targets: tuple[int, int]
    notes: tuple[str, ...] = ()


def element_condition(skill: DamageSkill, previous_attribute: int) -> ElementCondition:
    """EH multiplies effects; SD fixes target count; MN changes MP only."""
    for value in (skill.eh_multiplier, skill.element_sp_multiplier):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError('属性条件倍率必须是有限正数')
    if type(skill.spread_max_targets) is not bool:
        raise ValueError('SD条件标记无效')
    attributes = skill.element_attributes or (skill.attribute,)
    if (any(type(a) is not int or a not in range(1, 6) for a in attributes)
            or len(set(attributes)) != len(attributes)):
        raise ValueError('属性条件集合无效')
    targets = skill.min_targets, skill.max_targets
    if skill.eh_multiplier == 1 and not skill.spread_max_targets and skill.element_sp_multiplier == 1:
        return ElementCondition(1.0, targets)
    names = '火水风光暗'
    known = type(previous_attribute) is int and previous_attribute in range(1, 6)
    triggered = known and previous_attribute not in attributes
    if known:
        prefix = f'上一张{names[previous_attribute - 1]} → 本张{names[skill.attribute - 1]}'
        reason = '满足异属性条件' if triggered else '不满足异属性条件'
    else:
        prefix, reason = '上一张牌属性未知', '按未触发'
    notes = []
    if skill.eh_multiplier != 1:
        required = '/'.join(names[a - 1] for a in attributes)
        notes.append(f'{prefix}：EH {reason} ×{skill.eh_multiplier if triggered else 1:g}（要求上一张非{required}）')
    if skill.spread_max_targets:
        if triggered:
            targets = skill.max_targets, skill.max_targets
        notes.append(f'{prefix}：SD {reason}，范围{targets[0]}–{targets[1]}体；不乘单目标伤害')
    if skill.element_sp_multiplier != 1:
        notes.append(f'{prefix}：MN {reason}，MP×{skill.element_sp_multiplier if triggered else 1:g}；不乘伤害')
    return ElementCondition(skill.eh_multiplier if triggered else 1.0, targets, tuple(notes))
