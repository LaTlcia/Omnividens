"""Explicit recording lifecycle; sources and writers are injected."""
from __future__ import annotations
import math
from threading import Timer
from typing import Protocol
from lilyrex.domain.events import BattleEvent
from lilyrex.domain.ports import EventSource


class EventWriter(Protocol):
    bytes_written: int
    count: int
    def write_event(self, event: BattleEvent) -> None: ...
    def close(self) -> None: ...


def record(source: EventSource, writer: EventWriter, duration: float = 180,
           max_bytes: int = 50 * 1024 * 1024) -> dict:
    if not math.isfinite(duration) or duration <= 0 or max_bytes <= 0:
        raise ValueError("录制时长和容量必须为正数")
    timer = Timer(duration, source.close)
    timer.daemon = True
    timer.start()
    try:
        for event in source.events():
            writer.write_event(event)
            if writer.bytes_written >= max_bytes:
                break
    finally:
        timer.cancel()
        source.close()
        writer.close()
    return {"events": writer.count, "uncompressed_bytes": writer.bytes_written}
