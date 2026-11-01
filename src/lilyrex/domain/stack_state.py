"""Consume observed active-card stacks between authoritative history snapshots."""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from .events import BattleEvent


def _positive(value: Any) -> bool:
    return type(value) is int and value > 0


def _action(effect: Mapping[str, Any]) -> tuple[int, int, int] | None:
    key = tuple(effect.get(field) for field in ('actionUserId', 'cardMstId', 'skillMstId'))
    return key if all(_positive(value) for value in key) else None


def project_stack_state(history: Mapping[str, Any], event: BattleEvent) -> Mapping[str, Any]:
    """Project consumption only; later snapshots replace all projected counts.

    Toolbox consumes Mt/An/Et once per active action and Ba once per received
    damage line. Match the active card AND skill, so secondary passive effects
    cannot consume another layer. Guild hits and ball actions are not card hits.
    The broadcast has no stack grant targets: do not invent random recipients or
    interpret EH/MN/SD effect types 401..403 as stack changes. Counts are integers.
    Source histories/events stay immutable for backward and forked playback.
    """
    if event.name != 'response:gvg_skill_exec_player':
        return history
    effects = event.payload.get('influence')
    players = history.get('gvgUserData')
    stacks = history.get('gvgStackSkillData')
    if (not isinstance(effects, (list, tuple)) or not isinstance(players, (list, tuple))
            or not isinstance(stacks, Mapping)):
        return history
    rows = stacks.get('buff')
    if not isinstance(rows, (list, tuple)):
        return history
    known = {row['userId'] for row in players
             if isinstance(row, Mapping) and _positive(row.get('userId'))}
    active = {_action(effect) for effect in effects if isinstance(effect, Mapping)
              and type(effect.get('effectType')) is int and effect['effectType'] == 100}
    active.discard(None)
    spent: Counter[tuple[int, int]] = Counter()
    triggered: set[tuple[tuple[int, int, int], int]] = set()
    for effect in effects:
        if not isinstance(effect, Mapping):
            continue
        key = _action(effect)
        target, kind, value = (effect.get(field) for field in ('receivedUserId', 'effectType', 'effectValue'))
        if (key not in active or key[0] not in known or not _positive(target)
                or target not in known or type(kind) is not int or type(value) is not int):
            continue
        if kind == 1 and value >= 0:
            # Zero is still a hit (e.g. recording2669→2671→2675: Ba3→2).
            spent[target, 4] += 1
            triggered.add((key, 1))
        elif kind == 2 and value > 0:
            triggered.add((key, 3))
        elif (4 <= kind <= 11 or 211 <= kind <= 230) and -20 <= value <= 20:
            triggered.add((key, 2))
        elif kind == 101 and value >= 0:
            # Max-HP buff: observed levels reach 40, unlike the ordinary ±20.
            triggered.add((key, 2))
    for key, stack_type in triggered:
        spent[key[0], stack_type] += 1
    if not spent:
        return history
    updated = []
    changed = False
    for row in rows:
        if isinstance(row, Mapping):
            uid, kind, count = (row.get(field) for field in ('userId', 'stackType', 'stackNum'))
            if _positive(uid) and type(kind) is int and type(count) is int and spent[uid, kind]:
                remaining = max(0, count - spent[uid, kind])
                if remaining != count or remaining == 0:
                    changed = True
                    if remaining:
                        updated.append(dict(row, stackNum=remaining))
                    continue
        updated.append(row)
    return dict(history, gvgStackSkillData=dict(stacks, buff=updated)) if changed else history
