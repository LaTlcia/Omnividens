"""Stepwise quadratic skill growth from battle elapsed time, in seconds."""
from __future__ import annotations
import math


def charge_bonus(elapsed_seconds: float | None, *, minimum: float,
                 maximum: float, interval_seconds: int = 60,
                 full_seconds: int = 600) -> float:
    """Return the skill-specific bonus, before adding one to form a multiplier.

    The vertex is at elapsed zero. Time is rounded down to completed intervals;
    floating-point arithmetic happens only after that discrete step. Unknown or
    pre-battle time uses the minimum, and time after full charge stays capped.
    """
    try:
        if any(isinstance(v, bool) or not isinstance(v, (int, float))
               or not math.isfinite(v) for v in (minimum, maximum)):
            raise ValueError
        if minimum < 0 or maximum < minimum:
            raise ValueError
        if (type(interval_seconds) is not int or type(full_seconds) is not int
                or interval_seconds <= 0 or full_seconds <= 0
                or full_seconds % interval_seconds):
            raise ValueError
        if elapsed_seconds is None:
            return float(minimum)
        if (isinstance(elapsed_seconds, bool) or not isinstance(elapsed_seconds, (int, float))
                or not math.isfinite(elapsed_seconds)):
            raise ValueError
        complete = math.floor(max(0.0, min(elapsed_seconds, full_seconds)) / interval_seconds)
        fraction = complete * interval_seconds / full_seconds
        return float(minimum + (maximum - minimum) * fraction * fraction)
    except (ValueError, OverflowError):
        raise ValueError('蓄力时间或成长参数无效') from None
