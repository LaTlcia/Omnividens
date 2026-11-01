"""Identity-free event summaries shared by CLI analysis and benchmarks."""
from __future__ import annotations
from collections import Counter
from lilyrex.domain.ports import EventSource


def analyze(source: EventSource) -> dict:
    counts: Counter[str] = Counter()
    first = last = None
    try:
        for event in source.events():
            counts[event.name] += 1
            first = event.received_at if first is None else first
            last = event.received_at
    finally:
        source.close()
    result = {"events": sum(counts.values()), "event_counts": dict(sorted(counts.items())),
              "duration_seconds": max(0, last - first) if first is not None else 0}
    for attr in ("records", "rx_frames", "decoded_payload_bytes"):
        if hasattr(source, attr):
            result[attr] = getattr(source, attr)
    return result
