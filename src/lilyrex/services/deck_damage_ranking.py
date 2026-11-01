"""Batch current-state previews with a single-context cache; no I/O."""
from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Protocol

from lilyrex.domain.card_ranking import (
    CardDamageRank, CardDamageScore, rank_damage_cards, summarize_card_damage,
)
from lilyrex.domain.models import BattleSnapshot, PreviewResult


class DamagePreviewPort(Protocol):
    snapshot: BattleSnapshot

    def preview(self, user_id: int, card_id: int, skill_id: int,
                *, include_calculation: bool = True) -> PreviewResult: ...


class DeckDamageRankingService:
    def __init__(self, preview: DamagePreviewPort) -> None:
        self.preview = preview
        self._cache_preview: DamagePreviewPort | None = None
        self._cache_snapshot: BattleSnapshot | None = None
        self._cache_key: tuple | None = None
        self._cache_result: Mapping[int, CardDamageRank] = MappingProxyType({})

    def rank(self, user_id: int, cards: Mapping[int, int],
             *, revision: int) -> Mapping[int, CardDamageRank]:
        preview = self.preview
        snapshot = preview.snapshot
        card_pairs = tuple(cards.items())
        actor = snapshot.players.get(user_id)
        key = (revision, user_id, actor.deck_id if actor else None, card_pairs)
        if (self._cache_preview is preview and self._cache_snapshot is snapshot
                and self._cache_key == key):
            return self._cache_result
        targets = frozenset(p.user_id for p in snapshot.players.values()
                            if actor is not None and p.guild_id != actor.guild_id
                            and p.guild_id > 0 and p.party_sequence == 1 and p.hp > 0)
        unavailable = ('当前快照缺少攻击者基础面板' if actor is None else
                       '当前没有存活敌前排' if not targets else None)
        failures: dict[int, CardDamageRank] = {}
        scores: list[CardDamageScore] = []
        for card_id, skill_id in card_pairs:
            reason = unavailable
            if reason is None:
                result = preview.preview(user_id, card_id, skill_id, include_calculation=False)
                reason = result.error
                if reason is None and (result.card_id, result.skill_id) != (card_id, skill_id):
                    reason = '伤害预估与当前卡牌/技能不匹配'
                if reason is None and {row.target_user_id for row in result.estimates} != targets:
                    reason = '敌前排目标预估不完整，未参与排名'
                if reason is None:
                    try:
                        scores.append(summarize_card_damage(card_id, skill_id, result.estimates))
                    except ValueError as exc:
                        reason = str(exc)
            if reason is not None:
                failures[card_id] = CardDamageRank(card_id, skill_id, reason=reason)
        ranked = {row.card_id: row for row in rank_damage_cards(scores)}
        result_map = MappingProxyType({card_id: ranked.get(card_id) or failures[card_id]
                                       for card_id, _ in card_pairs})
        # Retain the objects themselves: reused object ids must never hit the cache.
        self._cache_preview, self._cache_snapshot = preview, snapshot
        self._cache_key, self._cache_result = key, result_map
        return result_map

    def invalidate(self) -> None:
        self._cache_preview = None
        self._cache_snapshot = None
        self._cache_key = None
        self._cache_result = MappingProxyType({})
