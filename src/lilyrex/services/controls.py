"""Control policy independent of concrete network clients."""
from typing import Callable
from lilyrex.domain.ports import ControlPort


class ViewingControls:
    """Enforce current-view policy at the send boundary, including stale clicks."""
    def __init__(self, delegate: ControlPort, allowed: Callable[[], bool]):
        self.delegate, self.allowed = delegate, allowed

    @property
    def enabled(self) -> bool:
        return bool(getattr(self.delegate, 'enabled', True) and self.allowed())

    def send(self, user_id: int, room_id: str, command: str) -> tuple[bool, str]:
        if not self.enabled:
            return False, 'history_disabled'
        return self.delegate.send(user_id, room_id, command)

    def counts(self) -> tuple[int, int]:
        return self.delegate.counts()

    def stop_all(self) -> None:
        self.delegate.stop_all()


class DisabledControls:
    enabled = False
    def send(self, user_id: int, room_id: str, command: str) -> tuple[bool, str]:
        return False, "replay_disabled"

    def counts(self) -> tuple[int, int]:
        return 0, 0

    def stop_all(self) -> None:
        pass
