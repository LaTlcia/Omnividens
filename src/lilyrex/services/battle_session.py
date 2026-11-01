"""Ordered battle state, deck knowledge and previews; no I/O or Tk imports."""
from __future__ import annotations
from collections import deque
from dataclasses import replace
from typing import Any, Callable, Mapping
from lilyrex.domain.deck_tracker import DeckTracker
from lilyrex.domain.events import BattleEvent
from lilyrex.domain.models import BattleSnapshot
from lilyrex.services.damage_preview import DamagePreviewService


class BattleSession:
    def __init__(self, preview: DamagePreviewService,
                 snapshot_factory: Callable[[Mapping[str, Any]], BattleSnapshot]) -> None:
        self.preview = preview
        self.snapshot_factory = snapshot_factory
        self.deck = DeckTracker()
        self.latest_history: Mapping[str, Any] = {}
        self.snapshot = BattleSnapshot()
        self.revision = 0
        self.event_count = 0
        self._last_key: tuple[int, int] | None = None
        self._hp_events: deque[tuple[int, int, int]] = deque()

    def _sync_deck(self, uid: int) -> None:
        if hasattr(self.preview, "update_deck"):
            cards, _, size, *_ = self.deck.view(uid)
            self.preview.update_deck(uid, self.deck.deck_id.get(uid), cards,
                                     expected_size=size, complete=False)

    def consume(self, event: BattleEvent, *, warmup: bool = False) -> None:
        key = (event.connection_generation, event.sequence)
        if self._last_key is not None and key <= self._last_key:
            raise ValueError("事件接收顺序回退或重复")
        self._last_key = key
        self.event_count += 1
        payload = event.payload
        if event.name == "response:gvg_system_schedule_info":
            history = payload.get("gvgSituationHistory")
            if not isinstance(history, Mapping):
                return
            first = not self.latest_history
            self.latest_history = history
            self.snapshot = self.snapshot_factory(history)
            if first:
                self.deck.fresh = self.snapshot.elapsed_seconds < 0
            for uid, player in self.snapshot.players.items():
                self.deck.set_deck(uid, player.deck_id)
                self._sync_deck(uid)
            self.preview.update(self.snapshot)
        elif event.name == "response:gvg_change_deck":
            influence = payload.get("influence") or [{}]
            uid = payload.get("userId") or payload.get("actionUserId") or influence[0].get("actionUserId")
            if uid:
                self.deck.change_deck(int(uid))
                self._sync_deck(int(uid))
        elif event.name in ("response:gvg_skill_exec_player", "response:gvg_neun_welt_charge"):
            charge = event.name.endswith("neun_welt_charge")
            for effect in payload.get("influence", []):
                kind = effect.get("effectType")
                if effect.get("cardMstId") and (charge or kind == 100):
                    uid, card = int(effect['actionUserId']), int(effect['cardMstId'])
                    skill = 0 if charge else int(effect.get('skillMstId') or 0)
                    self.deck.use(uid, card, skill)
                    self._sync_deck(uid)
                if not warmup and kind in (1, 2) and effect.get("receivedUserId"):
                    self._hp_events.append((int(effect['receivedUserId']), int(kind), int(effect.get('effectValue', 0))))
        if (self.latest_history and self.snapshot.timestamp > 0 and event.server_time is not None
                and event.server_time >= self.snapshot.timestamp):
            delta = event.server_time - self.snapshot.timestamp
            self.snapshot = replace(self.snapshot, timestamp=event.server_time,
                                    elapsed_seconds=self.snapshot.elapsed_seconds + delta)
            self.preview.update(self.snapshot)
        self.revision += 1

    def drain_hp_events(self) -> list[tuple[int, int, int]]:
        events = list(self._hp_events)
        self._hp_events.clear()
        return events
