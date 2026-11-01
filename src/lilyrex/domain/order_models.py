"""Order evaluation results, separate from connection and broadcast schemas."""
from dataclasses import dataclass


@dataclass(frozen=True)
class OrderModifiers:
    damage_multiplier: float = 1.0
    passive_rate_up: float = 0.0
    passive_rate_down: float = 0.0
    active_types: frozenset[int] = frozenset()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PendingOrderEffect:
    guild_id: int
    effect_id: int
    remaining_uses: int
    target_guild_id: int = 0
