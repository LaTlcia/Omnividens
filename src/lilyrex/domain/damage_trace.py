"""Explain the exact inputs and resolved factors used by a damage estimate."""
from __future__ import annotations

import math

from .buff_scaling import elemental_buff_ratio, normal_buff_ratio
from .models import BattlePlayer, DamageRange, DamageSkill, ModifierResult


def number(value: float) -> str:
    return f'{value:,.6f}'.rstrip('0').rstrip('.') if value != 0 else '0'


def _stat(player: BattlePlayer, skill: DamageSkill, *, attack: bool, value: float) -> str:
    stats = player.stats
    assert stats is not None
    magical = skill.attack_type == 'magical'
    if attack:
        left, right = stats.atk, stats.sp_atk
        level = player.buffs.sp_atk if magical else player.buffs.atk
        element = player.buffs.elemental_attack.get(skill.attribute, 0)
        symbol, label = 'A', 'Sp.ATK' if magical else 'ATK'
    else:
        left, right = stats.defense, stats.sp_defense
        level = player.buffs.sp_defense if magical else player.buffs.defense
        element = player.buffs.elemental_defense.get(skill.attribute, 0)
        symbol, label = 'D', 'Sp.DEF' if magical else 'DEF'
    base = right if magical else left
    return (f'{symbol} ({label}) = max(1, {number(base)} × (1 + {normal_buff_ratio(level):g})'
            f' + ({number(left)} + {number(right)}) / 2 × {elemental_buff_ratio(element):g})'
            f' = {number(value)}\n普通{level:+d}层；{"火水风光暗"[skill.attribute - 1]}属性{element:+d}层')


def damage_trace(skill: DamageSkill, actor: BattlePlayer, target: BattlePlayer,
                 attack: float, defense: float, factors: ModifierResult,
                 damage: DamageRange) -> tuple[str, ...]:
    """Numbers come from the computation; no second set of damage coefficients."""
    ratio = min(10, math.floor(attack / defense)) if attack < 10 * defense else 10
    factor_text = ' × '.join(f'{label}[{number(value)}]' for label, value in factors.factors)
    return (
        f'目标 #{target.rank} {target.name}' + ('（倒地）' if target.hp <= 0 else ''),
        _stat(actor, skill, attack=True, value=attack),
        _stat(target, skill, attack=False, value=defense),
        f'M = {factor_text} = {number(factors.multiplier)}',
        f'R = min(10, floor(A / D)) = {ratio}',
        f'C = max(1, (A − 2D / 3) × M × (1 + 0.05R))\n'
        f'  = max(1, ({number(attack)} − 2 × {number(defense)} / 3)'
        f' × {number(factors.multiplier)} × {number(1 + .05 * ratio)}) = {number(damage.core)}',
        f'p = {number(factors.crit_rate)}（暴击概率）；Ba = {number(factors.received_multiplier)}（目标减伤）',
        f'E ≈ (C × 0.95 + 100.5) × (1 + 0.3p) × Ba\n'
        f'  = ({number(damage.core)} × 0.95 + 100.5) × '
        f'{number(1 + .3 * factors.crit_rate)} × {number(factors.received_multiplier)}'
        f' ≈ {number(damage.expected)}',
        f'随机下界 = floor((C × 0.9 + 1) × {1.3 if factors.crit_rate == 1 else 1:g} × Ba) = {damage.minimum:,}',
        f'随机上界 = floor((C + 200) × {1.3 if factors.crit_rate > 0 else 1:g} × Ba) = {damage.maximum:,}',
    )
