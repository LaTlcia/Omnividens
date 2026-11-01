"""One-pass import of existing text captures, without retaining connection URLs."""
from __future__ import annotations
import re
from pathlib import Path
from .recording import RecordingWriter


def import_legacy(source: str | Path, output: str | Path) -> dict:
    pattern = re.compile(r"^\[([\d.]+)\] (<<|>>) (.*)$")
    writer = RecordingWriter(output)
    count = 0
    first = last = None
    try:
        with Path(source).open(encoding="utf-8") as stream:
            for line in stream:
                match = pattern.match(line.rstrip("\r\n"))
                if not match:
                    continue
                timestamp = float(match[1])
                # Outgoing packets may contain identity/authentication, and aren't played.
                if match[2] != "<<":
                    continue
                first = timestamp if first is None else first
                last = timestamp
                writer.write_row({"k": "rx", "t": timestamp, "raw": match[3],
                                  "n": len(match[3].encode("utf-8"))})
                count += 1
        if count == 0:
            raise ValueError("输入没有可导入的接收帧")
    finally:
        writer.close()
    return {"rx_frames": count, "duration_seconds": last - first, "output": str(output)}
