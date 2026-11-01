"""Observed action state: absolute buff levels and the most recent card attribute."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .events import BattleEvent


# UserActionEffectType in the client: buff/debuff pairs share the same setter.
_GENERAL_LEVELS = {
    4: 'physicalAttackEffectLevel', 8: 'physicalAttackEffectLevel',
    5: 'magicalAttackEffectLevel', 9: 'magicalAttackEffectLevel',
    6: 'physicalDefenseEffectLevel', 10: 'physicalDefenseEffectLevel',
    7: 'magicalDefenseEffectLevel', 11: 'magicalDefenseEffectLevel',
}


def _positive_integer(value: Any) -> bool:
    return type(value) is int and value > 0


def _set_scalar(row: Mapping[str, Any], field: str, value: int) -> Mapping[str, Any]:
    if type(row.get(field)) is int and row[field] == value:
        return row
    return dict(row, **{field: value})


def _set_element(row: Mapping[str, Any], field: str, attribute: int,
                 value: int) -> Mapping[str, Any]:
    original = row.get(field)
    levels = original if isinstance(original, (list, tuple)) else ()
    for index, entry in enumerate(levels):
        if (isinstance(entry, Mapping) and type(entry.get('attribute')) is int
                and entry['attribute'] == attribute):
            if type(entry.get('effectLevel')) is int and entry['effectLevel'] == value:
                return row
            updated = list(levels)
            updated[index] = dict(entry, effectLevel=value)
            return dict(row, **{field: updated})
    return dict(row, **{field: [*levels, {'attribute': attribute, 'effectLevel': value}]})


def project_action_state(history: Mapping[str, Any], event: BattleEvent,
                         card_attributes: Mapping[int, int]) -> Mapping[str, Any]:
    """Project only explicitly observed values, without mutating source frames.

    Buff effectValue is the resulting signed level, not a delta. Unknown effect
    types do not invent state. Card attributes use the same active-card records
    as deck tracking; an unknown observed card invalidates the prior attribute.
    Unchanged histories and untouched nested values retain their identities.
    """
    rows = history.get('gvgUserData')
    effects = event.payload.get('influence')
    if not isinstance(rows, (list, tuple)) or not isinstance(effects, (list, tuple)):
        return history
    players = {row['userId']: (index, row) for index, row in enumerate(rows)
               if isinstance(row, Mapping) and _positive_integer(row.get('userId'))}
    pending: dict[int, Mapping[str, Any]] = {}
    skill = event.name == 'response:gvg_skill_exec_player'
    charge = event.name == 'response:gvg_neun_welt_charge'
    for effect in effects:
        if not isinstance(effect, Mapping):
            continue
        kind, value = effect.get('effectType'), effect.get('effectValue')
        uid = effect.get('receivedUserId')
        if (_positive_integer(uid) and uid in players and type(kind) is int
                and type(value) is int and -20 <= value <= 20):
            row = pending.get(uid, players[uid][1])
            field = _GENERAL_LEVELS.get(kind)
            if field:
                pending[uid] = _set_scalar(row, field, value)
            elif 211 <= kind <= 230:
                offset = (kind - 211) % 10
                field = 'attributeAttackEffectLevel' if offset % 2 == 0 else 'attributeDefenseEffectLevel'
                pending[uid] = _set_element(row, field, offset // 2 + 1, value)

        if charge or (skill and type(kind) is int and kind == 100):
            actor_id, card_id = effect.get('actionUserId'), effect.get('cardMstId')
            if (_positive_integer(actor_id) and actor_id in players
                    and _positive_integer(card_id)):
                attribute = card_attributes.get(card_id)
                attribute = attribute if type(attribute) is int and 1 <= attribute <= 5 else 0
                row = pending.get(actor_id, players[actor_id][1])
                pending[actor_id] = _set_scalar(row, 'executedCardAttribute', attribute)

    changed = {uid: row for uid, row in pending.items() if row != players[uid][1]}
    if not changed:
        return history
    updated_rows = list(rows)
    for uid, row in changed.items():
        updated_rows[players[uid][0]] = row
    return dict(history, gvgUserData=updated_rows)
