"""Ordered battle state, deck knowledge and previews; no I/O or Tk imports."""
from __future__ import annotations
from collections import deque
from copy import copy, deepcopy
from dataclasses import replace
from types import MappingProxyType
from typing import Any, Callable, Mapping
from lilyrex.domain.deck_tracker import DeckTracker
from lilyrex.domain.events import BattleEvent
from lilyrex.domain.hp_effects import hp_changes, project_hp
from lilyrex.domain.action_state import project_action_state
from lilyrex.domain.stack_state import project_stack_state
from lilyrex.domain.models import BattleSnapshot
from lilyrex.services.damage_preview import DamagePreviewService


class BattleSession:
    def __init__(self, preview: DamagePreviewService,
                 snapshot_factory: Callable[[Mapping[str, Any]], BattleSnapshot],
                 card_attributes: Mapping[int, int] | None = None) -> None:
        self.preview = preview
        self.snapshot_factory = snapshot_factory
        self.card_attributes = MappingProxyType(dict(card_attributes or {}))
        self.deck = DeckTracker()
        self.latest_history: Mapping[str, Any] = {}
        self.snapshot = BattleSnapshot()
        self.revision = 0
        self.event_count = 0
        self._last_key: tuple[int, int] | None = None
        self._hp_events: deque[tuple[int, int, int]] = deque()
        self._view_token = object()
        self._continued_from: object | None = None

    def continues(self, previous: BattleSession) -> bool:
        """Whether this view is a staged forward continuation of that exact view."""
        return self._continued_from is previous._view_token

    def fork_for_view(self) -> BattleSession:
        """Stage forward navigation without mutating the currently displayed state.

        Catalogs and callbacks are fixed for the viewing session. Histories and
        frozen snapshots are replaced by consume, never mutated in place. Only
        deck knowledge and the observed passive pool need independent copies.
        Pending visual events belong to the original view and are not replayed.
        """
        preview = copy(self.preview)
        preview.passive_pool = deepcopy(self.preview.passive_pool)
        result = BattleSession(preview, self.snapshot_factory, self.card_attributes)
        result.deck = deepcopy(self.deck)
        result.latest_history, result.snapshot = self.latest_history, self.snapshot
        result.revision, result.event_count = self.revision, self.event_count
        result._last_key = self._last_key
        result._continued_from = self._view_token
        return result

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
        changes = hp_changes(payload.get('influence') or ())
        history, hit_points = project_hp(self.latest_history, changes)
        if hit_points:
            self.latest_history = history
            players = {uid: replace(player, hp=hit_points[uid]) if uid in hit_points else player
                       for uid, player in self.snapshot.players.items()}
            self.snapshot = replace(self.snapshot, players=players)
            self.preview.update(self.snapshot)
        if not warmup:
            self._hp_events.extend((change.user_id, change.kind, change.value) for change in changes)
        history = project_action_state(self.latest_history, event, self.card_attributes)
        history = project_stack_state(history, event)
        if history is not self.latest_history:
            self.latest_history = history
            projected = self.snapshot_factory(history)
            # Only player fields changed; preserve the logical clock and resolved
            # orders instead of resetting them to the last schedule's timestamp.
            self.snapshot = replace(self.snapshot, players=projected.players)
            self.preview.update(self.snapshot)
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
