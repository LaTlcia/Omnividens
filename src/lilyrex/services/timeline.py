"""Thread-safe metadata index over an injected event store; no payload retention."""
from __future__ import annotations
from bisect import bisect_left, bisect_right
import math
from threading import RLock
from typing import Literal
from lilyrex.domain.action_steps import ActionMarker, action_label
from lilyrex.domain.battle_time import BATTLE_SECONDS, BattleTimeMap, format_remaining
from lilyrex.domain.events import BattleEvent
from lilyrex.domain.playback import StepTarget, TimelineEntry, TimelinePoint, TimelineStore


class TimelineService:
    def __init__(self, store: TimelineStore):
        self.store = store
        self._lock = RLock()
        self._points: list[TimelinePoint] = []
        self._times: list[float] = []
        self._starts: dict[int, int] = {0: 1}
        self._known: dict[int, list[TimelinePoint]] = {0: []}
        self._elapsed: dict[int, list[float]] = {0: []}
        self._actions: dict[int, list[ActionMarker]] = {0: []}
        self._segment = 0
        self._complete = False
        self._mapping = BattleTimeMap()
        self._last_key: tuple[int, int] | None = None

    @property
    def complete(self) -> bool:
        with self._lock:
            return self._complete

    @property
    def latest(self) -> int:
        with self._lock:
            return len(self._points)

    @property
    def current_segment(self) -> int:
        with self._lock:
            return self._segment

    def append(self, event: BattleEvent, timeline_seconds: float) -> TimelinePoint:
        if (isinstance(timeline_seconds, bool) or not isinstance(timeline_seconds, (int, float))
                or not math.isfinite(timeline_seconds) or timeline_seconds < 0):
            raise ValueError("时间轴必须是有限非负秒数")
        key = event.connection_generation, event.sequence
        with self._lock:
            if self._complete:
                raise ValueError("时间线已结束，不能继续追加")
            if self._last_key is not None and key <= self._last_key:
                raise ValueError("事件接收顺序回退或重复")
            if self._times and timeline_seconds < self._times[-1]:
                raise ValueError("调度时间轴不能回退")
            mapping, new_battle, gap = self._mapping.project(event)
            ordinal = len(self._points) + 1
            segment = self._segment + int(new_battle)
            point = TimelinePoint(ordinal, segment, timeline_seconds, mapping.elapsed, gap)
            label = action_label(event)
            # Publish only the committed prefix. Storage failures leave metadata unchanged.
            self.store.append(TimelineEntry(ordinal, segment, event, timeline_seconds, mapping.elapsed))
            if new_battle:
                self._starts[segment] = ordinal
                self._known[segment], self._elapsed[segment] = [], []
                self._actions[segment] = []
            self._segment, self._mapping, self._last_key = segment, mapping, key
            self._points.append(point)
            self._times.append(timeline_seconds)
            if label is not None:
                self._actions[segment].append(ActionMarker(ordinal, label))
            if point.battle_elapsed is not None:
                self._known[segment].append(point)
                self._elapsed[segment].append(point.battle_elapsed)
            return point

    def finish(self) -> None:
        with self._lock:
            self._complete = True

    def point(self, ordinal: int) -> TimelinePoint:
        with self._lock:
            if not 1 <= ordinal <= len(self._points):
                raise KeyError(ordinal)
            return self._points[ordinal - 1]

    def segment_start(self, segment: int) -> int:
        with self._lock:
            return self._starts[segment]

    def bounds(self, segment: int | None = None) -> tuple[float, float] | None:
        """Inclusive integer-second inputs that fall within the captured range."""
        with self._lock:
            values = self._elapsed.get(self._segment if segment is None else segment, [])
            if not values:
                return None
            low = math.ceil(max(0, BATTLE_SECONDS - values[-1]))
            high = math.floor(max(0, BATTLE_SECONDS - values[0]))
            return (low, high) if low <= high else None

    def resolve_remaining(self, seconds: int, segment: int | None = None) -> tuple[TimelinePoint, str]:
        if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds < 0:
            raise ValueError("剩余时间必须为非负整数秒")
        with self._lock:
            segment = self._segment if segment is None else segment
            bounds = self.bounds(segment)
            if bounds is None:
                raise ValueError("还没有可跳转的比赛数据")
            if not bounds[0] <= seconds <= bounds[1]:
                raise ValueError(f"可跳转范围为 {format_remaining(bounds[0])}～{format_remaining(bounds[1])}")
            target = float('inf') if seconds == 0 else BATTLE_SECONDS - seconds
            values, points = self._elapsed[segment], self._known[segment]
            index = bisect_right(values, target) - 1
            if index < 0:
                raise ValueError("目标时间早于已收录的比赛数据")
            point = points[index]
            notes = []
            if index + 1 < len(points) and points[index + 1].gap and point.battle_elapsed < target:
                notes.append("该时段数据不连续")
            if point.battle_elapsed != target and seconds:
                notes.append(f"已定位到已收录的 {format_remaining(BATTLE_SECONDS - point.battle_elapsed)}")
            if any(p.gap for p in points[:index + 1]):
                notes.append("历史存在时间或接收缺口，记牌可能不完整")
            if values[0] > 0:
                notes.append("本次记录从比赛中途开始")
            return point, "；".join(notes)

    def read(self, after: int, through: int, limit: int = 64) -> tuple[TimelineEntry, ...]:
        with self._lock:
            through = min(through, len(self._points))
        return self.store.read(after, through, limit)

    def resolve_step(self, cursor: int, direction: Literal[-1, 1],
                     segment: int) -> StepTarget | None:
        """Stop exactly after one selected player action, within its segment.

        Synchronization before that action is consumed in order; later frames
        belong to the next step or resumed playback. Backward restores the
        previous action itself, without importing its following snapshots.
        The lock fixes the selected action while reception may continue.
        """
        if (type(direction) is not int or direction not in (-1, 1)
                or type(cursor) is not int or type(segment) is not int):
            raise ValueError('单步方向或游标无效')
        with self._lock:
            if segment not in self._starts:
                raise ValueError('单步比赛分段无效')
            start = self._starts[segment]
            end = self._starts.get(segment + 1, len(self._points) + 1) - 1
            if not start - 1 <= cursor <= end:
                raise ValueError('单步游标不在当前比赛分段')
            actions = self._actions[segment]
            next_index = bisect_right(actions, cursor, key=lambda action: action.ordinal)
            if direction == 1:
                if next_index >= len(actions):
                    return None
                selected = actions[next_index]
                through = selected.ordinal
            else:
                if next_index == 0:
                    return None
                selected = actions[next_index - 2] if next_index >= 2 else None
                through = selected.ordinal if selected else actions[0].ordinal - 1
            anchor = self._points[max(start, through) - 1].timeline_seconds
            return StepTarget(through, segment, anchor,
                              selected.ordinal if selected else None,
                              selected.label if selected else '动作开始前')

    def initial_cursor(self, start_seconds: float) -> int:
        """Last ordinal strictly before a CLI recording-time offset, or zero."""
        if not math.isfinite(start_seconds) or start_seconds < 0:
            raise ValueError("起点必须是有限非负秒数")
        with self._lock:
            return bisect_left(self._times, start_seconds)
