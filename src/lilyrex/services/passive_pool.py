"""Per-deck observation and explicit configured-pool selection; no file access."""
from __future__ import annotations
from typing import Mapping
from lilyrex.domain.passive_models import DeckCard, PassivePoolSettings


class PassivePool:
    def __init__(self) -> None:
        self._decks: dict[int, tuple[int | None, tuple[DeckCard, ...], int | None, bool]] = {}

    def update(self, user_id: int, deck_id: int | None, cards: Mapping[int, int],
               expected_size: int | None = None, complete: bool = False) -> None:
        self._decks[user_id] = (deck_id, tuple(DeckCard(c, s) for c, s in cards.items()), expected_size, complete)

    def select(self, user_id: int, deck_id: int | None, settings: PassivePoolSettings) -> tuple[tuple[DeckCard, ...], str]:
        if settings.mode == 'manual':
            return (), '手工UP模式：Order发动率不缩放聚合UP'
        mismatched = settings.mode == 'configured' and settings.deck_id is not None and settings.deck_id != deck_id
        if settings.mode == 'configured' and not mismatched:
            if len({c.card_id for c in settings.cards}) != len(settings.cards):
                raise ValueError('配置卡组存在重复卡')
            return settings.cards, f'配置被动池 {len(settings.cards)}张'
        state = self._decks.get(user_id)
        if state is None or state[0] != deck_id:
            return (), ('配置卡组不匹配，' if mismatched else '') + '已观测被动池 0 / ?，完整度未知'
        _, cards, size, complete = state
        return cards, ('配置卡组不匹配，' if mismatched else '') + f'已观测被动池 {len(cards)} / {size or "?"}，' + ('完整' if complete else '不完整估计')
