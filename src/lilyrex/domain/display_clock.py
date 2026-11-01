"""Receipt-based presentation clock, independent of combat calculations."""
from __future__ import annotations
from dataclasses import dataclass, replace
from .events import BattleEvent
from .battle_time import BattleTimeMap


@dataclass(frozen=True)
class DisplayClock:
    """Estimate subsecond battle time after a known schedule anchor.

    Receipt deltas supply display precision, not server-event accuracy. Integer
    schedule updates may move the estimate forward, but never erase fractions
    or rewind it within one battle. Keep a fixed anchor to avoid summed error.
    """
    elapsed: float | None = None
    anchor_elapsed: float | None = None
    anchor_received: float | None = None
    battle: BattleTimeMap = BattleTimeMap()
    stopped: bool = False

    def project(self, event: BattleEvent) -> DisplayClock:
        battle, new_battle, _ = self.battle.project(event)
        if event.name in ('response:gvg_out_time', 'response:room_leave'):
            return replace(self, battle=battle, stopped=True)
        if self.stopped and not new_battle:
            return replace(self, battle=battle)
        if battle.elapsed is None:
            return replace(self, battle=battle)
        received = float(event.received_at)
        if self.elapsed is None or new_battle:
            return DisplayClock(battle.elapsed, battle.elapsed, received, battle)
        reset_receipt = (self.battle.received is not None and received < self.battle.received
                         or self.battle.generation != event.connection_generation)
        if reset_receipt:
            elapsed = max(self.elapsed, battle.elapsed)
            return DisplayClock(elapsed, elapsed, received, battle)
        projected = self.anchor_elapsed + max(0.0, received - self.anchor_received)
        elapsed = max(self.elapsed, battle.elapsed, projected)
        if elapsed > projected:
            return DisplayClock(elapsed, elapsed, received, battle)
        return replace(self, elapsed=elapsed, battle=battle)


@dataclass(frozen=True)
class RunningDisplayClock:
    """Read-only interpolation in a caller-owned monotonic/timeline coordinate.

    Ordinary observations only correct forward; navigation creates a new clock
    at the exact event time. This clock never advances a combat session.
    """
    elapsed: float | None = None
    position: float = 0.0
    stopped: bool = False

    def at(self, position: float) -> float | None:
        if self.elapsed is None or self.stopped:
            return self.elapsed
        return self.elapsed + max(0.0, position - self.position)

    def observe(self, elapsed: float | None, position: float,
                stopped: bool = False) -> RunningDisplayClock:
        if self.stopped:
            return self
        current = self.at(position)
        if current is not None:
            elapsed = current if elapsed is None else max(current, elapsed)
        return RunningDisplayClock(elapsed, position, stopped)

    def freeze(self, position: float) -> RunningDisplayClock:
        return RunningDisplayClock(self.at(position), position, True)
