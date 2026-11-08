"""Player HP changes from observed action effects; never mutate source frames."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HpChange:
    user_id: int
    kind: int
    value: int
    killed: bool = False

    def __post_init__(self) -> None:
        if (type(self.user_id) is not int or self.user_id <= 0
                or type(self.kind) is not int or self.kind not in (1, 2)
                or type(self.value) is not int or self.value < 0
                or type(self.killed) is not bool):
            raise ValueError('玩家HP效果字段无效')


def hp_changes(effects: Iterable[Mapping[str, Any]]) -> tuple[HpChange, ...]:
    """Select observed player damage/healing, preserving broadcast order.

    Guild/siege effects use a zero player target and never belong to player HP.
    All arithmetic stays in integer HP units; malformed effects are ignored.
    """
    result = []
    for effect in effects:
        if not isinstance(effect, Mapping):
            continue
        try:
            result.append(HpChange(effect.get('receivedUserId'), effect.get('effectType'),
                                   effect.get('effectValue'), effect.get('killed', False)))
        except ValueError:
            continue
    return tuple(result)


def effective_max_hp(player: Mapping[str, Any]) -> int | None:
    """Read the broadcast HP cap, including its current HP modifier."""
    base, extra = player.get('maxHp'), player.get('maxHpEffect', 0)
    if type(base) is not int or base < 0 or type(extra) is not int:
        return None
    return max(0, base + extra)


def project_hp(history: Mapping[str, Any], changes: tuple[HpChange, ...]
               ) -> tuple[Mapping[str, Any], dict[int, int]]:
    """Return a copied history and changed HP values for known valid players.

    Only the history map, player list and modified player rows are copied. An
    unchanged result returns the original history object. Authoritative future
    snapshots can replace this projection without altering the source frames.
    """
    rows = history.get('gvgUserData')
    if not changes or not isinstance(rows, (list, tuple)):
        return history, {}
    players = {row['userId']: (index, row) for index, row in enumerate(rows)
               if isinstance(row, Mapping) and type(row.get('userId')) is int
               and row['userId'] > 0 and type(row.get('hp')) is int and row['hp'] >= 0}
    pending: dict[int, int] = {}
    for change in changes:
        found = players.get(change.user_id)
        if found is None:
            continue
        _, player = found
        hp = pending.get(change.user_id, player['hp'])
        if change.kind == 1:
            hp = 0 if change.killed else max(0, hp - change.value)
        else:
            hp += change.value
            limit = effective_max_hp(player)
            if limit is not None:
                hp = min(limit, hp)
        pending[change.user_id] = hp
    changed = {uid: hp for uid, hp in pending.items() if hp != players[uid][1]['hp']}
    if not changed:
        return history, {}
    updated_rows = list(rows)
    for uid, hp in changed.items():
        index, player = players[uid]
        updated_rows[index] = dict(player, hp=hp)
    return dict(history, gvgUserData=updated_rows), changed
