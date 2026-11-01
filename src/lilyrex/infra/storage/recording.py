"""Streaming legacy JSONL/GZ and version 2 decoded-event recordings."""
from __future__ import annotations
import gzip
import json
import math
from pathlib import Path
from typing import Iterator
from lilyrex.domain.events import BattleEvent
from lilyrex.infra.event_decoder import decode_event, decode_frame


class RecordingSource:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._stream = None
        self.closed = False
        self.records = self.rx_frames = self.decoded_payload_bytes = 0

    def events(self) -> Iterator[BattleEvent]:
        self.closed = False
        self.records = self.rx_frames = self.decoded_payload_bytes = 0
        opener = gzip.open if self.path.suffix == ".gz" else open
        line_number = 0
        try:
            with opener(self.path, "rt", encoding="utf-8") as stream:
                self._stream = stream
                for line_number, line in enumerate(stream, 1):
                    if self.closed:
                        break
                    self.records += 1
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError
                    if row.get("k") not in ("rx", "event"):
                        continue
                    timestamp = float(row.get("t", 0))
                    if not math.isfinite(timestamp):
                        raise ValueError
                    self.rx_frames += 1
                    if row["k"] == "event":
                        event = decode_event(row["name"], {"payload": row["payload"]},
                                             line_number, timestamp, int(row.get("generation", 0)))
                        self.decoded_payload_bytes += len(line.encode("utf-8"))
                    else:
                        raw = row.get("raw", "")
                        if row.get("b64"):
                            continue  # old binary attachments aren't standalone business events
                        if not isinstance(raw, str):
                            raise ValueError
                        self.decoded_payload_bytes += len(raw.encode("utf-8"))
                        event = decode_frame(raw, line_number, timestamp)
                    if event is not None:
                        yield event
        except (OSError, EOFError, UnicodeError, ValueError, TypeError, KeyError):
            if not self.closed:
                raise ValueError(f"录制读取失败：{self.path}，行 {line_number}") from None
        finally:
            self._stream = None

    def close(self) -> None:
        # Reader owns the handle; cancellation is safe from another thread.
        self.closed = True


class RecordingWriter:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        opener = gzip.open if self.path.suffix == ".gz" else open
        self._stream = opener(self.path, "xt", encoding="utf-8")
        self.bytes_written = 0
        self.count = 0
        self.write_row({"k": "meta", "schema_version": 2})

    def write_row(self, row: dict) -> None:
        text = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        self._stream.write(text)
        self.bytes_written += len(text.encode("utf-8"))

    def write_event(self, event: BattleEvent) -> None:
        self.write_row({"k": "event", "t": event.received_at, "name": event.name,
                        "payload": event.payload, "generation": event.connection_generation})
        self.count += 1

    def close(self) -> None:
        self._stream.close()
