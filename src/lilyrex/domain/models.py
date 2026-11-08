"""Shared contracts. Domain objects never import Tk, files, or sockets."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Protocol
from .attributes import AttributeValues


@dataclass(frozen=True)
class BaseStats:
    atk: float
    sp_atk: float
    defense: float
    sp_defense: float


@dataclass(frozen=True)
class BuffLevels:
    atk: int = 0
    sp_atk: int = 0
    defense: int = 0
    sp_defense: int = 0
    elemental_attack: Mapping[int, int] = field(default_factory=dict)
    elemental_defense: Mapping[int, int] = field(default_factory=dict)


@dataclass(frozen=True)
class BattlePlayer:
    user_id: int
    guild_id: int
    rank: int
    name: str
    stats: BaseStats | None
    buffs: BuffLevels
    hp: int = 0
    party_sequence: int = 1
    enemy_target_rank: int = 0
    job_card_type: int = 0
    last_attribute: int = 0
    attack_stacks: int = 0
    defense_stacks: int = 0
    deck_id: int | None = None


@dataclass(frozen=True)
class DamageSkill:
    skill_id: int
    card_id: int
    name: str
    card_name: str
    attribute: int
    card_type: int
    attack_type: Literal["physical", "magical"]
    magnification: float
    min_targets: int = 1
    max_targets: int = 1
    add_magnification: float = 0.0
    tactics_types: tuple[int, ...] = ()
    max_charge_bonus: float = 0.0
    eh_multiplier: float = 1.0
    ct_multiplier: float = 1.0
    unsupported: tuple[str, ...] = ()
    min_charge_bonus: float = 0.0
    charge_interval_seconds: int = 60
    charge_full_seconds: int = 600
    element_attributes: tuple[int, ...] = ()
    spread_max_targets: bool = False
    element_sp_multiplier: float = 1.0


@dataclass(frozen=True)
class OrderEffect:
    effect_id: int
    type: int = 0
    target_attribute: int = 0
    second_attribute: int = 0
    target_card_type: int = 0
    up: float = 0.0
    up2: float = 0.0
    down: float = 0.0
    down2: float = 0.0
    disadvantage_up: float = 0.0
    physical_reduction: float = 0.0
    magical_reduction: float = 0.0
    unsupported: tuple[str, ...] = ()
    physical_up: float | None = None
    magical_up: float | None = None
    passive_rate_up: float = 0.0
    passive_rate_down: float = 0.0
    enemy_attribute: int = 0
    enemy_attack_up: float = 0.0
    terminate_remaining: float = 0.0
    terminate_point_ratio: float = 0.0
    preparation_override: float = 0.0
    enemy_duration_override: float = 0.0
    state_only: bool = False


@dataclass(frozen=True)
class ActiveOrder:
    guild_id: int
    effect_id: int
    start: float
    end: float
    dual_effect_id: int = 0
    dual_status: int = 0
    dual_user_id: int = 0
    is_dual: bool = False
    parent_effect_id: int = 0


@dataclass(frozen=True)
class BattleSnapshot:
    players: Mapping[int, BattlePlayer] = field(default_factory=dict)
    points: Mapping[int, int] = field(default_factory=dict)
    orders: tuple[ActiveOrder, ...] = ()
    timestamp: float = 0.0
    elapsed_seconds: float = 0.0
    warnings: tuple[str, ...] = ()
    pending_orders: tuple = ()
    elapsed_time_known: bool = True


@dataclass(frozen=True)
class EstimateSettings:
    skill_level: float = 1.5
    benefit: float = 1.1
    charm_bonus: AttributeValues | float = field(default_factory=lambda: AttributeValues.filled(0.0))
    adx: float = 1.0
    theme: AttributeValues | float = field(default_factory=lambda: AttributeValues.filled(1.0))
    up_bonus: float = 0.0
    crit_rate: float = 0.05
    charge_fraction: float = 0.0
    costume_match_multiplier: float = 1.15


@dataclass(frozen=True)
class ModifierResult:
    multiplier: float
    received_multiplier: float
    crit_rate: float
    notes: tuple[str, ...] = ()
    factors: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True)
class DamageRange:
    expected: float
    minimum: float
    maximum: float
    core: float


@dataclass(frozen=True)
class DamageEstimate:
    target_user_id: int
    target_rank: int
    target_name: str
    expected: float
    minimum: float
    maximum: float
    attack: float
    defense: float
    locked: bool = False


@dataclass(frozen=True)
class PreviewResult:
    card_id: int
    skill_id: int
    card_name: str = ""
    attribute: int = 0
    attack_label: str = ""
    targets: tuple[int, int] = (1, 1)
    estimates: tuple[DamageEstimate, ...] = ()
    assumptions: tuple[str, ...] = ()
    error: str | None = None
    calculation: tuple[str, ...] = ()


class DamageCatalog(Protocol):
    def card_type(self, card_id: int, skill_id: int) -> int | None: ...
    def skill(self, card_id: int, skill_id: int) -> DamageSkill | None: ...
    def order(self, effect_id: int) -> OrderEffect | None: ...
