"""Per-connection Engine.IO 3 adapter using websockets permessage-deflate.

Unlike the archived adapter this module never patches websocket-client globals.
Only decoded bytes are counted reliably; TLS/framing bytes are unknown (None).
"""
from __future__ import annotations
from typing import Iterable, Mapping
import websocket
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect


class DeflateWS:
    def __init__(self, conn):
        self.conn = conn
        self.timeout: float | None = None
        self.decoded_payload_bytes = 0
        self.compressed_ws_bytes: int | None = None

    @property
    def compression_negotiated(self) -> bool:
        return any(getattr(ext, "name", "") == "permessage-deflate"
                   for ext in self.conn.protocol.extensions)

    def recv(self):
        try:
            value = self.conn.recv(timeout=self.timeout)
            self.decoded_payload_bytes += len(value.encode("utf-8") if isinstance(value, str) else value)
            return value
        except ConnectionClosed:
            raise websocket.WebSocketConnectionClosedException("WebSocket已关闭") from None
        except TimeoutError:
            raise websocket.WebSocketTimeoutException("WebSocket接收超时") from None

    def send(self, data, *args, **kwargs):
        try:
            self.conn.send(data)
        except ConnectionClosed:
            raise websocket.WebSocketConnectionClosedException("WebSocket已关闭") from None

    def send_binary(self, data):
        self.send(bytes(data))

    def close(self, *args, **kwargs):
        self.conn.close()

    def settimeout(self, value):
        self.timeout = value

    def getheaders(self):
        return dict(self.conn.response.headers) if self.conn.response else {}


def create_connection(url: str, header: Mapping[str, str] | Iterable[str] | None = None,
                      cookie: str | None = None, *, proxy_url: str | None = None,
                      compression: bool = True, connect_timeout: float = 30) -> DeflateWS:
    if isinstance(header, Mapping):
        headers = list(header.items())
    else:
        headers = [tuple(part.strip() for part in item.split(":", 1)) for item in (header or ())]
    if cookie:
        headers.append(("Cookie", cookie))
    try:
        connection = connect(url, additional_headers=headers, compression="deflate" if compression else None,
                             user_agent_header=None, proxy=proxy_url or None,
                             open_timeout=connect_timeout, ping_interval=None,
                             close_timeout=2, max_size=2 ** 24)
    except Exception:
        raise websocket.WebSocketException("WebSocket连接失败（请检查连接配置）") from None
    return DeflateWS(connection)
