"""Interruptible system clock implementation."""
from __future__ import annotations
import time
from threading import Event


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def wait_until(self, deadline: float, stop: Event) -> bool:
        return not stop.wait(max(0.0, deadline - self.monotonic()))
