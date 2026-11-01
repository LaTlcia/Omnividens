"""Battle time parsing and conservative mapping of received event prefixes."""
from __future__ import annotations
from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_HALF_UP
import math
import re
from typing import Mapping
from .events import BattleEvent

BATTLE_SECONDS = 900


def parse_remaining(raw: str) -> int:
    """Accept the displayed MM:SS clock, including pre-battle minutes above 15."""
    if not isinstance(raw, str) or not re.fullmatch(r"[0-9]+:[0-5][0-9]", raw.strip()):
        raise ValueError("请输入剩余时间 MM:SS，秒数为 00～59")
    minutes, seconds = raw.strip().split(":")
    try:
        return int(minutes) * 60 + int(seconds)
    except ValueError:
        raise ValueError("输入的分钟数过长") from None


def format_remaining(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    if isinstance(seconds, bool) or not math.isfinite(seconds):
        raise ValueError("剩余时间必须是有限秒数")
    whole = int(max(0, seconds))
    return f"{whole // 60:02d}:{whole % 60:02d}"



def format_remaining_microseconds(seconds: float | None) -> str:
    """Round the displayed float to integer microseconds, with decimal half-up."""
    if seconds is None:
        return "--:--"
    if isinstance(seconds, bool) or not math.isfinite(seconds):
        raise ValueError("剩余时间必须是有限秒数")
    micros = int((Decimal(str(max(0, seconds))) * 1_000_000)
                 .to_integral_value(rounding=ROUND_HALF_UP))
    whole, fraction = divmod(micros, 1_000_000)
    return f"{whole // 60:02d}:{whole % 60:02d}.{fraction:06d}"


def _number(raw: object) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    result = float(raw)
    return result if math.isfinite(result) else None


@dataclass(frozen=True)
class BattleTimeMap:
    """Small immutable state; a failed cache append cannot advance its clock.

    A later snapshot may carry the same integer elapsed second after an event
    interpolated within that second. Keeping a monotone envelope prevents a seek
    from pulling that event backwards across the requested time boundary.
    """
    elapsed: float | None = None
    anchor_elapsed: float | None = None
    anchor_server: float | None = None
    anchor_received: float | None = None
    received: float | None = None
    generation: int | None = None

    def project(self, event: BattleEvent) -> tuple[BattleTimeMap, bool, bool]:
        """Return (next state, new battle, discontinuity), without changing self."""
        general: Mapping = {}
        if event.name == "response:gvg_system_schedule_info":
            history = event.payload.get("gvgSituationHistory")
            candidate = history.get("general") if isinstance(history, Mapping) else None
            if isinstance(candidate, Mapping):
                general = candidate
        observed = _number(general.get("elapsedTimeSeconds"))
        server = _number(event.server_time)
        received = _number(event.received_at)
        if received is None:
            raise ValueError("接收时间必须是有限秒数")
        new_battle = (observed is not None and self.anchor_elapsed is not None and (
            (self.anchor_elapsed >= 0 and observed < -5 and self.anchor_elapsed - observed > 60)
            or (self.anchor_elapsed >= BATTLE_SECONDS - 60 and observed < 60
                and self.anchor_elapsed - observed > 600)))
        changed_connection = self.generation is not None and event.connection_generation != self.generation
        gap = changed_connection or (self.received is not None and received - self.received > 5)
        if new_battle:
            return BattleTimeMap(observed, observed, server, received, received,
                                 event.connection_generation), True, False
        state = replace(self, received=received, generation=event.connection_generation)
        # These terminal/room notifications can continue long after the final
        # battle snapshot. They provide no evidence that the battle clock moved.
        if event.name in ('response:gvg_out_time', 'response:room_leave'):
            return state, False, gap
        if observed is not None:
            if self.anchor_elapsed is not None:
                gap |= observed < self.anchor_elapsed or observed - self.anchor_elapsed > 5
            if server is not None and self.anchor_server is not None:
                gap |= server < self.anchor_server
            state = replace(state, anchor_elapsed=observed, anchor_server=server,
                            anchor_received=received)
            candidate_elapsed = observed
        elif self.anchor_elapsed is not None:
            if server is not None and self.anchor_server is not None and server >= self.anchor_server:
                delta = server - self.anchor_server
            else:
                delta = max(0.0, received - (self.anchor_received or 0.0))
                gap |= server is not None and self.anchor_server is not None and server < self.anchor_server
            candidate_elapsed = self.anchor_elapsed + delta
        else:
            return state, False, gap
        elapsed = candidate_elapsed if self.elapsed is None else max(self.elapsed, candidate_elapsed)
        return replace(state, elapsed=elapsed), False, gap
