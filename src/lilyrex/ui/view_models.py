"""Presentation contracts, independent of protocol envelopes and storage."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, TypedDict


@dataclass(frozen=True)
class UiResources:
    chara_data: Mapping[str, Mapping[str, Any]]
    order_data: Mapping[str, Mapping[str, Any]]
    card_data: Mapping[int, tuple[str, int, int]]
    skill_names: Mapping[int, str]
    assets_path: Path


class PlayerView(TypedDict, total=False):
    userId: int
    guildDataId: int
    name: str
    memberRank: int
    partySequence: int
    characterJobMstId: int
    hp: int
    maxHp: int
    maxHpEffect: int
    sp: int
    executedCardAttribute: int
    ownTargetMemberRank: int
    enemyTargetMemberRank: int
    isAuto: bool
    isCpu: bool
    isSpRecoveryMode: bool
    physicalAttackEffectLevel: int
    physicalDefenseEffectLevel: int
    magicalAttackEffectLevel: int
    magicalDefenseEffectLevel: int
    attributeAttackEffectLevel: list[dict[str, int]]
    attributeDefenseEffectLevel: list[dict[str, int]]


@dataclass(frozen=True)
class BattleView:
    guilds: tuple[Mapping[str, int], ...]
    players: tuple[PlayerView, ...]
    stacks: Mapping[str, Any]
    orders: tuple[Mapping[str, Any], ...]
    pending_orders: tuple[Mapping[str, Any], ...]
    ball: Mapping[str, Any]
    elapsed_seconds: float
    server_time: float
    revision: int
    display_elapsed_seconds: float | None = None
