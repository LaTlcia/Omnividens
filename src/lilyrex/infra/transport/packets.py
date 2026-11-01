"""Existing room/control envelopes; no credentials or configuration defaults."""
from __future__ import annotations
import json
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lilyrex.config import ConnectionConfig, IdentityConfig


def join_packet(connection: ConnectionConfig, identity: IdentityConfig) -> str:
    return json.dumps({"request_timestamp": int(time.time() * 1000),
                       "uuid": identity.uuid, "user_id": identity.user_id,
                       "room_id": connection.room_id,
                       "payload": json.dumps({"room_id": connection.room_id}),
                       "custom_headers": {"Accept": "application/json", "User-Agent": identity.user_agent},
                       "redirect_url": "http://app/reflector/reflector_app/join_room"}, ensure_ascii=True)


def control_packet(user_id: int, room_id: str, command: str, user_agent: str) -> tuple[str, str]:
    routes = {"join": ("room_join", "join_room", {"room_id": room_id}),
              "leave": ("room_leave", "leave_room", {"room_id": room_id}),
              "set_auto": ("server", "change_auto_mode", ""),
              "set_target": ("server", "set_target_member_rank", {"ownTargetMemberRank": 0, "enemyTargetMemberRank": 0})}
    if command not in routes:
        raise ValueError("不支持的控制命令")
    event, route, payload = routes[command]
    return event, json.dumps({"request_timestamp": int(time.time() * 1000), "uuid": str(user_id),
                              "user_id": user_id, "room_id": room_id, "payload": json.dumps(payload),
                              "custom_headers": {"Accept": "application/json", "User-Agent": user_agent,
                                                 "Content-Type": "application/json"},
                              "redirect_url": f"http://app/reflector/gvg_battle/{route}"}, ensure_ascii=True)
