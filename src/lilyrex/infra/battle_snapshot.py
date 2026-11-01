"""Convert a received history into a read-only domain snapshot; never connect."""
from __future__ import annotations

import math
from types import MappingProxyType
from typing import Any, Mapping

from lilyrex.domain.models import ActiveOrder, BaseStats, BattlePlayer, BattleSnapshot, BuffLevels
from lilyrex.domain.order_models import PendingOrderEffect


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value) if not isinstance(value, bool) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _elements(items: Any) -> Mapping[int, int]:
    return MappingProxyType({_integer(x.get("attribute")): _integer(x.get("effectLevel"))
                             for x in items if isinstance(x, dict)}) if isinstance(items, list) else MappingProxyType({})


def _stats(user: Mapping[str, Any]) -> BaseStats | None:
    keys = ("physicalAttack", "magicalAttack", "physicalDefense", "magicalDefense")
    try:
        values = [float(user[k]) for k in keys]
    except (KeyError, ValueError, TypeError, OverflowError):
        return None
    if not all(math.isfinite(v) and v >= 0 for v in values) or not any(values):
        return None
    return BaseStats(*values)


def snapshot_from_history(history: Mapping[str, Any],
                          job_card_types: Mapping[int, int] | None = None) -> BattleSnapshot:
    """Times use the replay/server clock, never the host wall clock."""
    general = history.get("general") or {}
    now = _integer(general.get("time"))
    elapsed = general.get("elapsedTimeSeconds")
    try:
        elapsed_known = (not isinstance(elapsed, bool) and isinstance(elapsed, (int, float))
                         and math.isfinite(elapsed))
    except OverflowError:
        elapsed_known = False
    warnings: list[str] = []
    if not now:
        warnings.append("缺少服务器时间：Order未计入")
    stacks: dict[tuple[int, int], int] = {}
    for entry in (history.get("gvgStackSkillData") or {}).get("buff", []):
        if not isinstance(entry, dict):
            continue
        key = (_integer(entry.get("userId")), _integer(entry.get("stackType")))
        stacks[key] = stacks.get(key, 0) + max(0, _integer(entry.get("stackNum")))
    players: dict[int, BattlePlayer] = {}
    for user in history.get("gvgUserData", []):
        if not isinstance(user, dict) or "userId" not in user:
            continue
        uid = _integer(user["userId"])
        players[uid] = BattlePlayer(
            user_id=uid, guild_id=_integer(user.get("guildDataId")), rank=_integer(user.get("memberRank")),
            name=str(user.get("name") or f"#{_integer(user.get('memberRank'))}"), stats=_stats(user),
            buffs=BuffLevels(
                atk=_integer(user.get("physicalAttackEffectLevel")),
                sp_atk=_integer(user.get("magicalAttackEffectLevel")),
                defense=_integer(user.get("physicalDefenseEffectLevel")),
                sp_defense=_integer(user.get("magicalDefenseEffectLevel")),
                elemental_attack=_elements(user.get("attributeAttackEffectLevel")),
                elemental_defense=_elements(user.get("attributeDefenseEffectLevel"))),
            hp=_integer(user.get("hp")), party_sequence=_integer(user.get("partySequence")),
            enemy_target_rank=_integer(user.get("enemyTargetMemberRank")),
            job_card_type=(job_card_types or {}).get(_integer(user.get("characterJobMstId")), 0),
            last_attribute=_integer(user.get("executedCardAttribute")),
            attack_stacks=stacks.get((uid, 1), 0), defense_stacks=stacks.get((uid, 4), 0),
            deck_id=_integer(user["deckDataId"]) if user.get("deckDataId") is not None else None)
    points = {_integer(g["guildDataId"]): _integer(g["point"])
              for g in history.get("guildData", []) if isinstance(g, dict) and "guildDataId" in g and "point" in g}
    orders: list[ActiveOrder] = []
    seen: set[tuple[int, int, int, int]] = set()
    for order in history.get("gvgTacticsData", []):
        if not isinstance(order, dict):
            continue
        start, end = _integer(order.get("startTime")), _integer(order.get("endTime"))
        if now and start <= now < end:
            key = (_integer(order.get("guildDataId")), _integer(order.get("tacticsEffectMstId")), start, end)
            if key not in seen:
                orders.append(ActiveOrder(*key, _integer(order.get('dualTacticsEffectMstId')),
                                          _integer(order.get('dualTacticsStatus')),
                                          _integer(order.get('dualTacticsUserId'))))
                seen.add(key)
    pending = tuple(PendingOrderEffect(_integer(x.get('guildDataId')), _integer(t.get('tacticsEffectMstId')),
                                      _integer(x.get('effectNum')), _integer(t.get('targetGuildId')))
                    for x in history.get('gvgStackTacticsData', []) if isinstance(x, dict)
                    for t in x.get('tacticsDataList', []) if isinstance(t, dict) and _integer(x.get('effectNum')) > 0)
    if any(_integer(x.get("startTime")) <= now < _integer(x.get("endTime"))
           for x in history.get("rareSkill", []) if isinstance(x, dict)):
        warnings.append("活动RS额外乘区未计入")
    return BattleSnapshot(MappingProxyType(players), MappingProxyType(points), tuple(orders), now,
                          elapsed if elapsed_known else 0.0, tuple(dict.fromkeys(warnings)), pending,
                          elapsed_time_known=elapsed_known)
