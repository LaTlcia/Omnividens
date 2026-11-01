"""Pure replay scheduling; server offsets are measured from an anchor, not accumulated."""
from __future__ import annotations
from dataclasses import dataclass
import math
from typing import Iterable, Iterator
from .events import BattleEvent, ReplayOptions


def validate_options(options: ReplayOptions) -> None:
    if options.timing not in ("recorded", "server", "burst"):
        raise ValueError("timing必须为recorded/server/burst")
    for name, value, positive in (("speed", options.speed, True),
                                  ("start", options.start_seconds, False),
                                  ("seconds", options.run_seconds, True)):
        if value is None and name == "seconds":
            continue
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0 or (positive and value == 0)):
            raise ValueError(f"{name}必须是有限{'正' if positive else '非负'}数")


@dataclass(frozen=True)
class ScheduledEvent:
    event: BattleEvent
    timeline_seconds: float
    due_seconds: float
    warmup: bool
    clock_fallback: bool = False


def schedule(events: Iterable[BattleEvent], options: ReplayOptions) -> Iterator[ScheduledEvent]:
    validate_options(options)
    first_received = first_server = anchor_received = None
    server_base = anchor_due = last_due = 0.0
    for event in events:
        if first_received is None:
            first_received = event.received_at
        recorded = max(0.0, event.received_at - first_received)
        due = recorded
        fallback = False
        if options.timing == "server":
            if event.server_time is not None:
                if first_server is None:
                    first_server, server_base = event.server_time, max(last_due, recorded)
                candidate = server_base + event.server_time - first_server
                if candidate < last_due:
                    # Keep order and re-anchor after a server clock reset/regression.
                    fallback = True
                    first_server, server_base = event.server_time, max(last_due, recorded)
                    candidate = server_base
                due = anchor_due = candidate
                anchor_received = event.received_at
            elif anchor_received is not None:
                due = anchor_due + max(0.0, event.received_at - anchor_received)
            else:
                fallback = True
        due = max(last_due, due)
        last_due = due
        warmup = due < options.start_seconds
        if warmup and not options.warmup:
            continue
        wait = 0.0 if warmup or options.timing == "burst" else (due - options.start_seconds) / options.speed
        yield ScheduledEvent(event, due, wait, warmup, fallback)
