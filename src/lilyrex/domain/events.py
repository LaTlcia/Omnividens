"""Decoded event contract shared by live reception and recording playback."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class BattleEvent:
    sequence: int
    name: str
    payload: Mapping[str, Any]
    received_at: float = 0.0
    server_time: float | None = None
    connection_generation: int = 0


@dataclass(frozen=True)
class ReplayOptions:
    timing: str = "server"
    speed: float = 1.0
    start_seconds: float = 0.0
    run_seconds: float | None = None
    warmup: bool = True
