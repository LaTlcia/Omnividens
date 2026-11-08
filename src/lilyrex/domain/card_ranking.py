"""Pure card-damage aggregation, competition ranks and display ordering."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math

from .models import BattlePlayer, DamageEstimate


EMPTY_LETHAL_PERCENTAGES: tuple[int | None, ...] = (None, None, None, None)


@dataclass(frozen=True)
class CardDamageScore:
    card_id: int
    skill_id: int
    avg_expected: float
    max_expected: float
    target_ids: tuple[int, ...]


@dataclass(frozen=True)
class CardDamageRank:
    card_id: int
    skill_id: int
    avg_expected: float | None = None
    max_expected: float | None = None
    avg_rank: int | None = None
    max_rank: int | None = None
    reason: str | None = None
    lethal_percentages: tuple[int | None, ...] = EMPTY_LETHAL_PERCENTAGES


def _valid_damage(value: float) -> bool:
    return math.isfinite(value) and value >= 0


def lethal_percentages(estimates: Sequence[DamageEstimate],
                       frontline: Mapping[int, BattlePlayer]) -> tuple[int | None, ...]:
    """Floor expected damage as a percentage of effective max HP for enemy ranks 1–4."""
    damage_by_user: dict[int, float | None] = {}
    for estimate in estimates:
        uid = estimate.target_user_id
        damage_by_user[uid] = None if uid in damage_by_user else estimate.expected

    by_rank: dict[int, int | None] = {}
    for player in frontline.values():
        rank = player.rank
        if rank not in range(1, 5):
            continue
        expected = damage_by_user.get(player.user_id)
        if (rank in by_rank or expected is None or not _valid_damage(expected)
                or player.max_hp is None or player.max_hp <= 0):
            by_rank[rank] = None
            continue
        # Floor the binary64 estimate exactly, including values just below 100%.
        numerator, denominator = expected.as_integer_ratio()
        by_rank[rank] = (100 * numerator) // (denominator * player.max_hp)
    return tuple(by_rank.get(rank) for rank in range(1, 5))


def summarize_card_damage(card_id: int, skill_id: int,
                          estimates: Sequence[DamageEstimate]) -> CardDamageScore:
    """Aggregate expected damage equally across unique targets, without rounding."""
    targets = tuple(item.target_user_id for item in estimates)
    if not targets or len(set(targets)) != len(targets):
        raise ValueError("伤害排名需要非空且不重复的目标")
    values = tuple(item.expected for item in estimates)
    if not all(_valid_damage(value) for value in values):
        raise ValueError("伤害排名需要有限且非负的期望伤害")
    try:
        average = math.fsum(values) / len(values)
    except OverflowError as exc:
        raise ValueError("伤害期望聚合超出有限数值范围") from exc
    return CardDamageScore(card_id, skill_id, average, max(values), targets)


def rank_damage_cards(scores: Sequence[CardDamageScore]) -> tuple[CardDamageRank, ...]:
    """Return ranks in input order; exact ties use competition ranks (1, 1, 3)."""
    if len({score.card_id for score in scores}) != len(scores):
        raise ValueError("伤害排名不能包含重复卡牌")
    for score in scores:
        if (not _valid_damage(score.avg_expected) or not _valid_damage(score.max_expected)
                or not score.target_ids or len(set(score.target_ids)) != len(score.target_ids)):
            raise ValueError("伤害排名指标或目标无效")

    def ranks(field: str) -> dict[int, int]:
        result: dict[int, int] = {}
        previous: float | None = None
        rank = 0
        for position, score in enumerate(sorted(scores, key=lambda s: getattr(s, field), reverse=True), 1):
            value = getattr(score, field)
            if value != previous:
                rank = position
            result[score.card_id] = rank
            previous = value
        return result

    average_ranks, maximum_ranks = ranks('avg_expected'), ranks('max_expected')
    return tuple(CardDamageRank(score.card_id, score.skill_id, score.avg_expected,
                                score.max_expected, average_ranks[score.card_id],
                                maximum_ranks[score.card_id]) for score in scores)


def order_ranked_cards(cards: Sequence[tuple[int, int]],
                       rankings: Mapping[int, CardDamageRank],
                       metric: str | None) -> tuple[tuple[int, int], ...]:
    """Sort matching ranked cards first; preserve ties and unranked input order."""
    if metric not in (None, 'avg', 'max'):
        raise ValueError("排序指标必须为avg、max或None")
    if metric is None:
        return tuple(cards)

    def key(card: tuple[int, int]) -> tuple[int, float]:
        row = rankings.get(card[0])
        if row is not None and (row.card_id, row.skill_id) == card and row.reason is None:
            rank = getattr(row, f'{metric}_rank')
            value = getattr(row, f'{metric}_expected')
            if isinstance(rank, int) and not isinstance(rank, bool) and rank > 0:
                if value is not None and _valid_damage(value):
                    return (0, -value)
        return (1, 0.0)

    return tuple(sorted(cards, key=key))
