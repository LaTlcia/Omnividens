"""Passive catalog and per-player assumptions."""
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class DeckCard:
    card_id: int
    skill_id: int
    passive_level_multiplier: float | None = None
    legendary_level: int | None = None


@dataclass(frozen=True)
class PassivePoolSettings:
    mode: Literal['observed', 'manual', 'configured'] = 'observed'
    level_multiplier: float = 1.5
    theme_attributes: tuple[int, ...] = ()
    cards: tuple[DeckCard, ...] = ()
    legendary_level: int = 0
    deck_id: int | None = None


@dataclass(frozen=True)
class PassiveEntry:
    source_card_id: int
    auto_skill_id: int
    host_attribute: int
    kind: str
    coefficient: float
    base_probability: float


@dataclass(frozen=True)
class LegendaryEntry:
    attribute: int
    attack_type: str
    up: float = 0.0
    crit: float = 0.0


@dataclass(frozen=True)
class CardPassives:
    card_id: int
    skill_id: int
    entries: tuple[PassiveEntry, ...] = ()
    legendary: tuple[tuple[LegendaryEntry, ...], ...] = ()


@dataclass(frozen=True)
class PassiveEstimate:
    up: float = 0.0
    crit: float = 0.0
    notes: tuple[str, ...] = ()
