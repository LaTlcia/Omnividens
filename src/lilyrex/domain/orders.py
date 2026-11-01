"""Resolve directional Order effects without replaying server-side state changes."""
from __future__ import annotations
import math
from .models import ActiveOrder, BattlePlayer, BattleSnapshot, DamageSkill, OrderEffect
from .order_models import OrderModifiers


def resolve_orders(skill: DamageSkill, actor: BattlePlayer, target: BattlePlayer,
                   snapshot: BattleSnapshot, orders: tuple[tuple[ActiveOrder, OrderEffect], ...],
                   theme: float = 1.0) -> OrderModifiers:
    gain = rate_up = rate_down = 0.0
    types: set[int] = set()
    notes: list[str] = []
    seen: set[tuple] = set()
    for active, effect in orders:
        if active.effect_id != effect.effect_id:
            raise ValueError("Order效果ID与主数据不一致")
        if not all(math.isfinite(x) for x in (active.start, active.end)) or active.end < active.start:
            raise ValueError("Order时间无效")
        if not active.start <= snapshot.timestamp < active.end:
            continue
        if active.guild_id not in (actor.guild_id, target.guild_id):
            continue
        key = (active.guild_id, active.effect_id, active.start, active.end, active.is_dual, active.parent_effect_id)
        if key in seen:
            continue
        seen.add(key)
        # These conditions are relative to the owner of the Order, not the attacker.
        other_gid = target.guild_id if active.guild_id == actor.guild_id else actor.guild_id
        owner_points, other_points = snapshot.points.get(active.guild_id), snapshot.points.get(other_gid)
        if effect.terminate_remaining and 900 - snapshot.elapsed_seconds < effect.terminate_remaining:
            notes.append("Order因剩余战斗时间条件结束")
            continue
        if effect.terminate_point_ratio:
            if owner_points is None or other_points is None:
                notes.append("Order终止积分条件未知，未计入该Order")
                continue
            if owner_points <= other_points * effect.terminate_point_ratio:
                notes.append("Order因持有阵营积分条件结束")
                continue
        if active.is_dual:
            parent = next((e for a, e in orders if not a.is_dual and a.effect_id == active.parent_effect_id
                           and a.guild_id == active.guild_id and a.start == active.start and a.end == active.end), None)
            if parent is None:
                continue
            if parent.terminate_remaining and 900 - snapshot.elapsed_seconds < parent.terminate_remaining:
                continue
            if parent.terminate_point_ratio and (owner_points is None or other_points is None
                    or owner_points <= other_points * parent.terminate_point_ratio):
                continue
        values = (effect.up, effect.up2, effect.down, effect.down2, effect.disadvantage_up,
                  effect.physical_reduction, effect.magical_reduction, effect.passive_rate_up,
                  effect.passive_rate_down, effect.enemy_attack_up)
        if any(not math.isfinite(v) or v < 0 for v in values):
            raise ValueError("Order参数必须是有限非负数")
        if active.is_dual:
            notes.append('Order追加按客户端显示条件推定生效，倍率同区相加，未由实伤校验')
        elif active.dual_effect_id and not any(a.is_dual and a.parent_effect_id == active.effect_id
                and a.guild_id == active.guild_id and a.start == active.start and a.end == active.end
                for a, _ in orders):
            notes.append(f"双重Order追加状态未判定（状态{active.dual_status}），追加效果未计入")
        notes.extend("未计入Order机制：" + x for x in effect.unsupported)
        if active.guild_id == actor.guild_id:
            types.add(effect.type)
            rate_up += effect.passive_rate_up / 100
            up = effect.physical_up if skill.attack_type == "physical" else effect.magical_up
            up = effect.up if up is None else up
            if not math.isfinite(up) or up < 0:
                raise ValueError("Order攻击系数无效")
            if effect.target_attribute == skill.attribute:
                gain += up / 100 * theme
            if effect.second_attribute == skill.attribute:
                gain += effect.up2 / 100 * theme
            if effect.target_card_type == skill.card_type:
                gain += up / 100
            if effect.disadvantage_up:
                if owner_points is None or other_points is None:
                    notes.append("阵营积分缺失，劣势指令增益按未触发")
                elif owner_points < other_points:
                    gain += effect.disadvantage_up / 100
        else:
            rate_down += effect.passive_rate_down / 100
            if effect.target_attribute == skill.attribute:
                gain -= effect.down / 100
            if effect.second_attribute == skill.attribute:
                gain -= (effect.down2 or effect.down) / 100
            if effect.target_card_type == skill.card_type:
                gain -= effect.down / 100
            gain -= (effect.physical_reduction if skill.attack_type == "physical" else effect.magical_reduction) / 100
            if effect.enemy_attribute == skill.attribute:
                gain += effect.enemy_attack_up / 100
    if not math.isfinite(gain) or gain < -1:
        raise ValueError("合计Order倍率必须为有限非负数")
    if gain or rate_up or rate_down:
        notes.insert(0, f"Order×{1+gain:.3g}；被动率己方+{rate_up:.0%}/敌方-{rate_down:.0%}")
    return OrderModifiers(1 + gain, rate_up, rate_down, frozenset(types), tuple(dict.fromkeys(notes)))
