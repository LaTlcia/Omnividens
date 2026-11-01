"""Resolve known battle modifiers plus explicitly configured unknown regions."""
from __future__ import annotations

import math

from .attributes import attribute_value
from .charge import charge_bonus
from .orders import resolve_orders
from .models import (
    ActiveOrder, BattlePlayer, BattleSnapshot, DamageSkill,
    EstimateSettings, ModifierResult, OrderEffect,
)


def _finite(name: str, value: float, *, positive: bool = False) -> float:
    try:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError
        result = float(value)
        if not math.isfinite(result) or result < 0 or (positive and result == 0):
            raise ValueError
    except (ValueError, OverflowError):
        suffix = "有限正数" if positive else "有限非负数"
        raise ValueError(f"{name}必须是{suffix}") from None
    return result


def calculate_modifiers(
    skill: DamageSkill,
    attacker: BattlePlayer,
    target: BattlePlayer,
    snapshot: BattleSnapshot,
    orders: tuple[tuple[ActiveOrder, OrderEffect], ...],
    settings: EstimateSettings,
) -> ModifierResult:
    """M excludes random and Ba; settings bonuses are fractions, orders percent.

    `adx` and `theme` are already resolved multipliers, not UI choice indices.
    Theme also multiplies friendly attribute-order gain, as in Agamotto. All
    setting-driven regions remain assumptions; no deck passives are invented.
    """
    if skill.attack_type not in ("physical", "magical"):
        raise ValueError("attack_type必须是physical或magical")
    if skill.attribute not in (1, 2, 3, 4, 5):
        raise ValueError("技能属性必须是1至5")
    for name in ("skill_level", "benefit", "adx", "costume_match_multiplier"):
        _finite(name, getattr(settings, name), positive=True)
    for name in ("up_bonus", "crit_rate", "charge_fraction"):
        _finite(name, getattr(settings, name))
    selected: dict[str, float] = {}
    for name in ("theme", "charm_bonus"):
        try:
            selected[name] = attribute_value(getattr(settings, name), skill.attribute, positive=name == "theme")
        except ValueError as exc:
            raise ValueError(f"{name}：{exc}") from None
    theme, charm = selected["theme"], selected["charm_bonus"]
    for name in ("crit_rate", "charge_fraction"):
        if getattr(settings, name) > 1:
            raise ValueError(f"{name}必须在0至1之间")
    for name in ("magnification", "eh_multiplier", "ct_multiplier"):
        _finite(name, getattr(skill, name), positive=True)
    for name in ("add_magnification", "min_charge_bonus", "max_charge_bonus"):
        _finite(name, getattr(skill, name))
    _finite("战斗时间戳", snapshot.timestamp)

    notes = [
        f"技能等级倍率按配置×{settings.skill_level:g}，恩惠×{settings.benefit:g}",
        f"{'火水风光暗'[skill.attribute - 1]}属性主题×{theme:g}，CHARM +{charm:.1%}；ADX及基础暴率按配置估计",
    ]
    own_points = snapshot.points.get(attacker.guild_id)
    other_points = snapshot.points.get(target.guild_id)
    losing: bool | None = None
    if own_points is not None and other_points is not None:
        _finite("己方积分", own_points)
        _finite("敌方积分", other_points)
        losing = own_points < other_points

    order_result = resolve_orders(skill, attacker, target, snapshot, orders, theme)
    command = order_result.damage_multiplier
    active_types = order_result.active_types
    notes.extend(order_result.notes)
    extra = skill.add_magnification if active_types.intersection(skill.tactics_types) else 0.0
    elapsed = snapshot.elapsed_seconds if snapshot.elapsed_time_known else None
    growth = charge_bonus(elapsed, minimum=skill.min_charge_bonus, maximum=skill.max_charge_bonus,
                          interval_seconds=skill.charge_interval_seconds, full_seconds=skill.charge_full_seconds)
    if skill.max_charge_bonus or skill.min_charge_bonus:
        if elapsed is None:
            notes.append(f"比赛经过时间未知，蓄力按最低档 +{growth:.2%}")
        else:
            step_seconds = math.floor(max(0.0, min(elapsed, skill.charge_full_seconds))
                                      / skill.charge_interval_seconds) * skill.charge_interval_seconds
            notes.append(f"蓄力第{step_seconds / 60:g}分钟：成长 +{growth:.2%}，满档 +{skill.max_charge_bonus:.2%}")
    magnification = (skill.magnification + extra) * (1 + growth)

    costume = 1.0
    if attacker.job_card_type == skill.card_type:
        costume = settings.costume_match_multiplier
    elif not attacker.job_card_type:
        notes.append("衣装主职未知，衣装增益按×1")
    eh = 1.0
    if skill.eh_multiplier != 1:
        if attacker.last_attribute not in (1, 2, 3, 4, 5):
            notes.append("上一张牌属性未知，EH按未触发")
        elif attacker.last_attribute != skill.attribute:
            eh = skill.eh_multiplier
    ct = 1.0
    if skill.ct_multiplier != 1:
        if losing:
            ct = skill.ct_multiplier
        elif losing is None:
            notes.append("阵营积分缺失，CT按未触发")
    if skill.unsupported:
        notes.append("未计入技能机制：" + "、".join(skill.unsupported))

    multiplier = (.1 * magnification * settings.skill_level * costume * settings.benefit
                  * (1 + charm) * settings.adx * theme
                  * (1 + settings.up_bonus) * command * ct * eh
                  * (1.2 if attacker.attack_stacks > 0 else 1.0))
    _finite("合计伤害倍率", multiplier)
    return ModifierResult(
        multiplier=multiplier,
        received_multiplier=.7 if target.defense_stacks > 0 else 1.0,
        crit_rate=settings.crit_rate,
        notes=tuple(dict.fromkeys(notes)),
    )
