"""Lazy, serialized existing controls; uncertain sends are never retried."""
from __future__ import annotations
from queue import Queue, Empty
from threading import Event, Lock, Thread
from typing import TYPE_CHECKING
from .socketio_client import connect_client, make_client
from .packets import control_packet

if TYPE_CHECKING:
    from lilyrex.config import ConnectionConfig, IdentityConfig


class _ControlSession:
    def __init__(self, connection: ConnectionConfig, identity: IdentityConfig):
        self.connection, self.identity = connection, identity
        self.client = make_client(connection)
        self.ready = Event()
        self.client.on("connect", self.ready.set, namespace=connection.namespace)
        self.client.on("disconnect", self.ready.clear, namespace=connection.namespace)
        self.stop = Event()
        self.queue: Queue = Queue()
        self.status = "idle"
        self.worker = Thread(target=self._run, daemon=True, name="gvg-control")
        self.worker.start()

    def _run(self) -> None:
        while not self.stop.is_set():
            try:
                user_id, room_id, command = self.queue.get(timeout=.1)
            except Empty:
                continue
            try:
                if not self.client.connected:
                    connect_client(self.client, self.connection)
                if not self.ready.wait(self.connection.connect_timeout):
                    raise TimeoutError
                if self.stop.is_set():
                    self.client.disconnect()
                    break
                event, packet = control_packet(user_id, room_id, command, self.identity.user_agent)
                self.client.emit(event, packet, namespace=self.connection.namespace)
                self.status = "sent"
            except Exception:
                self.status = "unconfirmed"  # do not retry toggles automatically

    def close(self) -> None:
        self.stop.set()
        try:
            self.client.disconnect()
        except Exception:
            pass
        self.worker.join(timeout=3)


class ControlPool:
    def __init__(self, connection: ConnectionConfig, identity: IdentityConfig):
        self.connection, self.identity = connection, identity
        self.sessions = {}
        self.lock = Lock()

    def send(self, user_id: int, room_id: str, command: str) -> tuple[bool, str]:
        if type(user_id) is not int or user_id <= 0 or command not in ("join", "leave", "set_auto", "set_target"):
            return False, "invalid_command"
        with self.lock:
            session = self.sessions.get(user_id)
            if session is None:
                session = self.sessions[user_id] = _ControlSession(self.connection, self.identity)
            session.queue.put((user_id, room_id, command))
            session.status = "queued"
        return True, "queued"

    def counts(self) -> tuple[int, int]:
        return sum(s.client.connected for s in self.sessions.values()), len(self.sessions)

    def stop_all(self) -> None:
        for session in list(self.sessions.values()):
            session.close()
