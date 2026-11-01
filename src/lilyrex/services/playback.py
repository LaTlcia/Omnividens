"""Incremental playback and history reconstruction; all sessions have one owner."""
from __future__ import annotations
from dataclasses import dataclass
import logging
from typing import Callable, Literal, Mapping
from lilyrex.domain.battle_time import BATTLE_SECONDS
from lilyrex.domain.events import ReplayOptions
from lilyrex.domain.playback import PlaybackStatus
from lilyrex.domain.replay_timeline import validate_options
from lilyrex.services.battle_session import BattleSession
from lilyrex.services.replay import PlaybackClock
from lilyrex.services.timeline import TimelineService


@dataclass
class _Rebuild:
    session: BattleSession
    cursor: int
    through: int
    segment: int
    anchor: float
    warmup: bool = True
    emit_ordinal: int | None = None


class PlaybackController:
    """Tk calls advance in short slices; reception/indexing runs independently."""

    def __init__(self, timeline: TimelineService,
                 new_session: Callable[[], BattleSession],
                 options: ReplayOptions | None, clock: PlaybackClock):
        if options is not None:
            validate_options(options)
        self.timeline, self.new_session = timeline, new_session
        self.options, self.clock = options, clock
        self.live_session = new_session()
        self.view_session = self.live_session
        self.mode = 'live' if options is None else 'replay'
        self._live_cursor = self._cursor = 0
        self._live_segment = self._segment = -1
        self._generation = 0
        self._rebuild: _Rebuild | None = None
        self._ready = options is None
        self._anchor_clock = self._anchor_timeline = 0.0
        self._notice = ''
        self._paused = False
        self._paused_at: float | None = None
        self._action_label = ''
        self._incomplete = bool(options and not options.warmup)
        self.consumed_events = self.warmup_events = 0

    @property
    def controls_enabled(self) -> bool:
        return self.options is None and self.mode == 'live' and self._rebuild is None

    def status(self) -> PlaybackStatus:
        session = self.view_session
        remaining = (max(0.0, BATTLE_SECONDS - session.snapshot.elapsed_seconds)
                     if session.latest_history else None)
        segment = self._segment if self.options and self._segment >= 0 else None
        available = self.timeline.bounds(segment) if self._ready else None
        end = (self.options is not None and self._ready and self._rebuild is None
               and self.timeline.complete and self._cursor >= self.timeline.latest)
        notice = self._notice
        if not self._ready:
            notice = '正在加载回放…'
        elif self._rebuild is not None:
            notice = '正在跳转…'
        elif self._incomplete:
            notice = '预热关闭，记牌可能不完整'
        elif end:
            notice = '播放结束，可跳转时间'
        navigable = (self._ready and self.mode != 'live' and self._rebuild is None
                     and self._segment >= 0)
        previous = following = None
        if navigable:
            previous = self.timeline.resolve_step(self._cursor, -1, self._segment)
            following = self.timeline.resolve_step(self._cursor, 1, self._segment)
        return PlaybackStatus(self.mode, remaining, available, self._rebuild is not None,
                              end, self.timeline.complete, notice, paused=self._paused,
                              can_pause=navigable and not end,
                              can_step_backward=previous is not None,
                              can_step_forward=following is not None,
                              action_label=self._action_label)

    def toggle_pause(self) -> None:
        if not self.status().can_pause:
            raise ValueError('当前状态不能暂停或继续，请等待加载完成或先进入回看')
        now = self.clock.monotonic()
        if self._paused:
            self._anchor_clock += now - self._paused_at
            self._paused, self._paused_at = False, None
            self._action_label = ''
        else:
            self._paused, self._paused_at = True, now
        logging.getLogger('lilyrex.playback').info('pause mode=%s paused=%s', self.mode, self._paused)

    def step(self, direction: Literal[-1, 1]) -> int:
        if type(direction) is not int or direction not in (-1, 1):
            raise ValueError('步进方向必须是-1或1')
        if self.mode == 'live' or not self._ready or self._rebuild is not None or self._segment < 0:
            raise ValueError('当前状态不能步进，请等待加载完成或先进入回看')
        target = self.timeline.resolve_step(self._cursor, direction, self._segment)
        if target is None:
            raise ValueError('没有上一个动作' if direction < 0 else '没有下一个动作')
        if direction > 0:
            # All mutable state is private until the entire suffix succeeds.
            session = self.view_session.fork_for_view()
            self._generation += 1
            self._rebuild = _Rebuild(session, self._cursor, target.ordinal,
                                     target.segment_id, target.timeline_seconds, warmup=False)
        else:
            self._begin(target.ordinal, target.segment_id, target.timeline_seconds)
            self._rebuild.emit_ordinal = target.action_ordinal
        self._paused, self._paused_at = True, self.clock.monotonic()
        self._action_label = target.label
        if target.action_ordinal is not None:
            entries = self.timeline.read(target.action_ordinal - 1, target.action_ordinal, 1)
            if entries:
                payload = entries[0].event.payload
                actor_id = payload.get('actionUserId') or payload.get('userId')
                actor_id = actor_id or next((row.get('actionUserId')
                    for row in (payload.get('influence') or ())
                    if isinstance(row, Mapping) and row.get('actionUserId')), None)
                actor = self.view_session.snapshot.players.get(actor_id) if type(actor_id) is int else None
                if actor is not None:
                    self._action_label = f'{actor.name[:18]} · {target.label}'
        logging.getLogger('lilyrex.playback').info('step request=%s direction=%s ordinal=%s',
                                                  self._generation, direction, target.ordinal)
        return self._generation

    def _begin(self, through: int, segment: int, anchor: float) -> None:
        self._generation += 1
        self._rebuild = _Rebuild(self.new_session(), self.timeline.segment_start(segment) - 1,
                                 through, segment, anchor)
        self._incomplete = False

    def seek_remaining(self, seconds: int) -> int:
        if not self._ready:
            raise ValueError('回放尚未加载完成')
        segment = self._segment if self.options and self._segment >= 0 else None
        point, notice = self.timeline.resolve_remaining(seconds, segment)
        self._notice = notice
        self._action_label = ''
        if self.options is None:
            self.mode = 'history'
            self.live_session.drain_hp_events()
        self._begin(point.ordinal, point.segment_id, point.timeline_seconds)
        logging.getLogger('lilyrex.playback').info('seek request=%s remaining=%s', self._generation, seconds)
        return self._generation

    def return_live(self) -> None:
        if self.options is not None:
            raise ValueError('离线回放不能回到直播')
        self._generation += 1
        self._rebuild = None
        self._paused, self._paused_at = False, None
        self._action_label = ''
        self.live_session.drain_hp_events()
        self.view_session = self.live_session
        self._cursor, self._segment = self._live_cursor, self._live_segment
        self.mode, self._notice = 'live', ''
        self._incomplete = False

    def _consume(self, session: BattleSession, entry, warmup: bool) -> None:
        session.consume(entry.event, warmup=warmup)
        self.consumed_events += 1
        self.warmup_events += warmup

    def _advance_live(self, deadline: float) -> None:
        head = self.timeline.latest
        handled = 0
        while self._live_cursor < head and handled < 256:
            entries = self.timeline.read(self._live_cursor, head, 16)
            if not entries:
                break
            for entry in entries:
                if entry.segment_id != self._live_segment:
                    if self._live_segment >= 0:
                        self.live_session = self.new_session()
                    self._live_segment = entry.segment_id
                showing_live = self.mode == 'live'
                self._consume(self.live_session, entry, not showing_live)
                self._live_cursor = entry.ordinal
                if showing_live:
                    self.view_session = self.live_session
                    self._cursor, self._segment = entry.ordinal, entry.segment_id
                handled += 1
                if self.clock.monotonic() >= deadline:
                    return

    def _start_replay(self) -> None:
        self._ready = True
        if not self.timeline.latest:
            return
        target = self.timeline.initial_cursor(self.options.start_seconds)
        point = self.timeline.point(max(1, target))
        self._segment = point.segment_id
        if self.options.warmup:
            self._begin(target, point.segment_id, self.options.start_seconds)
        else:
            self._cursor = target
            self._anchor_clock = self.clock.monotonic()
            self._anchor_timeline = self.options.start_seconds

    def _advance_rebuild(self, deadline: float) -> None:
        job = self._rebuild
        handled = 0
        while job.cursor < job.through and handled < 256:
            entries = self.timeline.read(job.cursor, job.through, 16)
            if not entries:
                raise RuntimeError('历史缓存缺少已提交事件')
            for entry in entries:
                self._consume(job.session, entry, job.warmup and entry.ordinal != job.emit_ordinal)
                job.cursor = entry.ordinal
                handled += 1
                if self.clock.monotonic() >= deadline:
                    return
        if job.cursor >= job.through:
            self.view_session = job.session
            self._cursor, self._segment = job.through, job.segment
            # Start the playback clock only after reconstruction has completed.
            self._anchor_timeline = job.anchor
            self._anchor_clock = self.clock.monotonic()
            self._paused_at = self._anchor_clock if self._paused else None
            self._rebuild = None

    def _advance_view(self, deadline: float) -> None:
        head, handled = self.timeline.latest, 0
        speed = self.options.speed if self.options else 1.0
        burst = bool(self.options and self.options.timing == 'burst')
        while self._cursor < head and handled < 256:
            entries = self.timeline.read(self._cursor, head, 16)
            if not entries:
                break
            for entry in entries:
                due = self._anchor_clock + (entry.timeline_seconds - self._anchor_timeline) / speed
                if not burst and due > self.clock.monotonic():
                    return
                if entry.segment_id != self._segment:
                    self.view_session = self.new_session()
                    self._segment = entry.segment_id
                self._consume(self.view_session, entry, False)
                self._cursor = entry.ordinal
                self._action_label = ''
                handled += 1
                if self.clock.monotonic() >= deadline:
                    return
        if self.mode == 'history' and self._cursor >= head and self._live_cursor >= head:
            self.return_live()

    def advance(self, budget_ms: float = 8.0) -> None:
        now = self.clock.monotonic()
        deadline = now + max(0.001, budget_ms / 1000)
        if self.options is None:
            live_deadline = deadline if self.mode == 'live' else now + (deadline - now) / 2
            self._advance_live(live_deadline)
            if self.mode == 'live':
                return
        elif not self._ready:
            if not self.timeline.complete:
                return
            self._start_replay()
        if self._rebuild is not None:
            self._advance_rebuild(deadline)
            return
        if self._paused:
            return
        self._advance_view(deadline)
