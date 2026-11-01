"""Decode known envelope fields once; never recursively parse names or messages."""
from __future__ import annotations
import json
import math
from typing import Any
from lilyrex.domain.events import BattleEvent


def decode_event(name: str, data: object, sequence: int, received_at: float = 0,
                 connection_generation: int = 0) -> BattleEvent:
    try:
        outer = json.loads(data) if isinstance(data, str) else data
        if not isinstance(outer, dict):
            raise ValueError
        payload = outer.get("payload", outer)
        if payload is None or payload == "":
            payload = {}
        elif isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            raise ValueError
        raw_time = (payload.get("gvgSituationHistory") or {}).get("general", {}).get("time")
        server_time = float(raw_time) if raw_time is not None else None
        if server_time is not None and not math.isfinite(server_time):
            raise ValueError
        return BattleEvent(sequence, name, payload, received_at, server_time, connection_generation)
    except (ValueError, TypeError, AttributeError):
        raise ValueError(f"事件解析失败：sequence={sequence}") from None


def decode_frame(raw: str, sequence: int, received_at: float = 0) -> BattleEvent | None:
    """Decode Engine.IO MESSAGE / Socket.IO EVENT, including namespace and ACK id."""
    if not raw.startswith("42"):
        return None
    start = raw.find("[")
    if start < 0:
        raise ValueError(f"Socket.IO帧无事件数组：sequence={sequence}")
    try:
        values: Any = json.loads(raw[start:])
        if not isinstance(values, list) or not values or not isinstance(values[0], str):
            raise ValueError
        return decode_event(values[0], values[1] if len(values) > 1 else {}, sequence, received_at)
    except (ValueError, TypeError):
        raise ValueError(f"Socket.IO事件帧无效：sequence={sequence}") from None
