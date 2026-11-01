"""Private SQLite event log; connections belong to individual worker threads."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
from threading import Lock, local

from lilyrex.domain.events import BattleEvent
from lilyrex.domain.playback import TimelineEntry


class TimelineStorageError(RuntimeError):
    """A storage failure whose message never contains event data or SQL values."""


class TemporaryTimelineStore:
    """Append-only local history, deleted by close after all workers have joined.

    Each thread owns its connection and cursors. check_same_thread=False only
    permits the lifecycle owner to close those connections after workers stop.
    Readers fetch bounded batches and never retain an active SQLite cursor.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._local = local()
        self._connections: list[sqlite3.Connection] = []
        self._closed = False
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        try:
            self._temporary = tempfile.TemporaryDirectory(prefix='lilyrex-history-')
            directory = Path(self._temporary.name)
            os.chmod(directory, 0o700)
            self.path = directory / 'events.sqlite3'
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            connection = sqlite3.connect(self.path, isolation_level=None)
            try:
                connection.execute('PRAGMA journal_mode=WAL').close()
                connection.execute('PRAGMA synchronous=NORMAL').close()
                connection.executescript('''
                    CREATE TABLE events (
                        ordinal INTEGER PRIMARY KEY,
                        segment_id INTEGER NOT NULL,
                        timeline_seconds REAL NOT NULL,
                        battle_elapsed REAL,
                        name TEXT NOT NULL,
                        received_at REAL NOT NULL,
                        server_time REAL,
                        generation INTEGER NOT NULL,
                        sequence INTEGER NOT NULL,
                        payload_json TEXT NOT NULL,
                        UNIQUE(generation, sequence)
                    );
                    CREATE INDEX events_segment_time
                        ON events(segment_id, battle_elapsed, ordinal);
                ''')
            finally:
                connection.close()
        except (OSError, sqlite3.Error):
            if self._temporary is not None:
                self._temporary.cleanup()
            raise TimelineStorageError('无法创建本机回看缓存') from None

    def _connection(self) -> sqlite3.Connection:
        with self._lock:
            if self._closed:
                raise TimelineStorageError('本机回看缓存已关闭')
            connection = getattr(self._local, 'connection', None)
            if connection is None:
                try:
                    connection = sqlite3.connect(self.path, timeout=5,
                        isolation_level=None, check_same_thread=False)
                    connection.execute('PRAGMA synchronous=NORMAL').close()
                except sqlite3.Error:
                    if connection is not None:
                        connection.close()
                    raise TimelineStorageError('无法打开本机回看缓存') from None
                self._connections.append(connection)
                self._local.connection = connection
            return connection

    @staticmethod
    def _values(entry: TimelineEntry) -> tuple:
        event = entry.event
        integers = (entry.ordinal, entry.segment_id, event.sequence, event.connection_generation)
        times = (entry.timeline_seconds, entry.battle_elapsed, event.received_at, event.server_time)
        if (any(type(value) is not int or value < 0 for value in integers)
                or entry.ordinal == 0 or not isinstance(event.name, str)
                or any(value is not None and (isinstance(value, bool)
                    or not isinstance(value, (int, float)) or not math.isfinite(value)) for value in times)):
            raise ValueError('回看事件的序号或时间无效')
        try:
            payload = json.dumps(dict(event.payload), ensure_ascii=False,
                                 separators=(',', ':'), allow_nan=False)
        except (TypeError, ValueError, OverflowError):
            raise ValueError('回看事件正文无法序列化') from None
        return (entry.ordinal, entry.segment_id, entry.timeline_seconds, entry.battle_elapsed,
                event.name, event.received_at, event.server_time, event.connection_generation,
                event.sequence, payload)

    def append(self, entry: TimelineEntry) -> None:
        values = self._values(entry)
        connection = self._connection()
        try:
            connection.execute('BEGIN IMMEDIATE').close()
            cursor = connection.execute('SELECT COALESCE(MAX(ordinal), 0) FROM events')
            try:
                previous = cursor.fetchone()[0]
            finally:
                cursor.close()
            if entry.ordinal != previous + 1:
                raise ValueError('回看事件序号必须连续递增')
            connection.execute('INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', values).close()
            connection.commit()
        except (sqlite3.Error, ValueError, OverflowError) as exc:
            try:
                connection.rollback()
            except sqlite3.Error:
                pass
            if isinstance(exc, ValueError):
                raise
            raise TimelineStorageError('本机回看缓存写入失败，历史不完整') from None

    def read(self, after: int, through: int, limit: int) -> tuple[TimelineEntry, ...]:
        if any(type(value) is not int or value < 0 for value in (after, through, limit)):
            raise ValueError('回看缓存读取范围无效')
        connection = self._connection()
        if limit == 0 or through <= after:
            return ()
        try:
            cursor = connection.execute(
                'SELECT * FROM events WHERE ordinal > ? AND ordinal <= ? ORDER BY ordinal LIMIT ?',
                (after, through, limit))
            try:
                rows = cursor.fetchall()
            finally:
                cursor.close()
            entries = []
            for row in rows:
                payload = json.loads(row[9])
                if not isinstance(payload, dict):
                    raise ValueError
                entries.append(TimelineEntry(row[0], row[1],
                    BattleEvent(row[8], row[4], payload, row[5], row[6], row[7]), row[2], row[3]))
            return tuple(entries)
        except (sqlite3.Error, ValueError, TypeError, OverflowError):
            raise TimelineStorageError('本机回看缓存读取失败') from None

    def latest_ordinal(self) -> int:
        connection = self._connection()
        try:
            cursor = connection.execute('SELECT COALESCE(MAX(ordinal), 0) FROM events')
            try:
                return int(cursor.fetchone()[0])
            finally:
                cursor.close()
        except sqlite3.Error:
            raise TimelineStorageError('无法读取本机回看缓存进度') from None

    def close(self) -> None:
        """Close once all callers are quiescent, including the reception thread."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            failed = False
            for connection in self._connections:
                try:
                    connection.close()
                except sqlite3.Error:
                    failed = True
            self._connections.clear()
            try:
                if self._temporary is not None:
                    self._temporary.cleanup()
            except OSError:
                failed = True
            if failed:
                raise TimelineStorageError('本机回看缓存清理失败') from None

    def __enter__(self) -> TemporaryTimelineStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
