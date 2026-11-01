"""Replay orchestration with injected source and clock; no network or Tk imports."""
from __future__ import annotations
from dataclasses import dataclass
from threading import Event
from typing import Callable, Iterator, Protocol
from lilyrex.domain.events import BattleEvent, ReplayOptions
from lilyrex.domain.ports import EventSource
from lilyrex.domain.replay_timeline import ScheduledEvent, schedule, validate_options


class PlaybackClock(Protocol):
    def monotonic(self) -> float: ...
    def wait_until(self, deadline: float, stop: Event) -> bool: ...


@dataclass
class ReplayReport:
    events: int = 0
    warmup_events: int = 0
    clock_fallbacks: int = 0
    completed: bool = False


class ReplayRunner:
    def __init__(self, source: EventSource, options: ReplayOptions, clock: PlaybackClock | None = None):
        validate_options(options)
        self.source, self.options, self.clock = source, options, clock

    def timed_events(self) -> Iterator[ScheduledEvent]:
        yield from schedule(self.source.events(), self.options)

    def run(self, consume: Callable[[BattleEvent, bool], None], stop: Event | None = None,
            before_playback: Callable[[], None] | None = None) -> ReplayReport:
        if self.clock is None:
            raise ValueError("ReplayRunner.run需要注入Clock")
        stop = stop or Event()
        report = ReplayReport()
        start = self.clock.monotonic()
        playback_start = None
        deadline = None if self.options.run_seconds is None else start + self.options.run_seconds
        try:
            for item in self.timed_events():
                if stop.is_set() or (deadline is not None and self.clock.monotonic() >= deadline):
                    break
                if not item.warmup and playback_start is None:
                    # GUI consumers can flush their queued warmup state before anchoring.
                    if before_playback is not None:
                        before_playback()
                    playback_start = self.clock.monotonic()
                target = (playback_start if playback_start is not None else start) + item.due_seconds
                if deadline is not None and target >= deadline:
                    self.clock.wait_until(deadline, stop)
                    break
                if not self.clock.wait_until(target, stop):
                    break
                consume(item.event, item.warmup)
                report.events += 1
                report.warmup_events += item.warmup
                report.clock_fallbacks += item.clock_fallback
            else:
                report.completed = True
        finally:
            self.source.close()
        return report
