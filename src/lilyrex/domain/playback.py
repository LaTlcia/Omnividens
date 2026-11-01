"""Contracts for local viewing history; independent of UI and storage."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Protocol
from .events import BattleEvent


@dataclass(frozen=True)
class TimelineEntry:
    ordinal: int
    segment_id: int
    event: BattleEvent
    timeline_seconds: float
    battle_elapsed: float | None


@dataclass(frozen=True)
class TimelinePoint:
    ordinal: int
    segment_id: int
    timeline_seconds: float
    battle_elapsed: float | None
    gap: bool = False


@dataclass(frozen=True)
class StepTarget:
    ordinal: int
    segment_id: int
    timeline_seconds: float
    action_ordinal: int | None
    label: str


@dataclass(frozen=True)
class PlaybackStatus:
    mode: Literal['live', 'history', 'replay']
    remaining_seconds: float | None = None
    available_remaining: tuple[float, float] | None = None
    seeking: bool = False
    at_end: bool = False
    source_complete: bool = False
    notice: str = ''
    paused: bool = False
    can_pause: bool = False
    can_step_backward: bool = False
    can_step_forward: bool = False
    action_label: str = ''


class TimelineStore(Protocol):
    def append(self, entry: TimelineEntry) -> None: ...
    def read(self, after: int, through: int, limit: int) -> tuple[TimelineEntry, ...]: ...
    def latest_ordinal(self) -> int: ...
    def close(self) -> None: ...


class PlaybackPort(Protocol):
    def status(self) -> PlaybackStatus: ...
    def seek_remaining(self, seconds: int) -> int: ...
    def return_live(self) -> None: ...
    def toggle_pause(self) -> None: ...
    def step(self, direction: Literal[-1, 1]) -> int: ...
