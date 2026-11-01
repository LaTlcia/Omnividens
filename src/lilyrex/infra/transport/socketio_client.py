"""Fixed Engine.IO 3 / Socket.IO 4 websocket-only adapter with ordered dispatch."""
from __future__ import annotations
import logging
from queue import Empty, Full, Queue
from threading import Event, Thread
import time
from typing import TYPE_CHECKING, Iterator
from urllib.parse import urlsplit, urlunsplit
import engineio.client
from engineio import exceptions, packet
import socketio
from lilyrex.infra.event_decoder import decode_event
from .lily_deflate import create_connection
from .packets import join_packet
from lilyrex.domain.events import BattleEvent

if TYPE_CHECKING:
    from lilyrex.config import ConnectionConfig, IdentityConfig


def _quiet_logger() -> logging.Logger:
    logger = logging.Logger("lilyrex.protocol.silent")
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    logger.disabled = True
    return logger


class OrderedEngineClient(engineio.client.Client):
    """Only MESSAGE handling differs: synchronous, before receiving the next packet."""
    ws_factory = None

    def _receive_packet(self, pkt):
        if pkt.packet_type == packet.MESSAGE:
            self._trigger_event("message", pkt.data, run_async=False)
        else:
            super()._receive_packet(pkt)

    def _connect_websocket(self, url, headers, engineio_path):
        # This application explicitly selects websocket; no polling upgrade path.
        if self.sid:
            raise exceptions.ConnectionError("不支持polling升级路径")
        self.base_url = self._get_engineio_url(url, engineio_path, "websocket")
        ws = None
        try:
            ws = self.ws_factory(self.base_url + self._get_url_timestamp(), header=headers)
            opening = packet.Packet(encoded_packet=ws.recv())
            if opening.packet_type != packet.OPEN:
                raise ValueError
            self.sid = opening.data["sid"]
            self.upgrades = opening.data.get("upgrades", [])
            self.ping_interval = int(opening.data["pingInterval"]) / 1000
            self.ping_timeout = int(opening.data["pingTimeout"]) / 1000
        except Exception:
            if ws is not None:
                ws.close()
            raise exceptions.ConnectionError("WebSocket握手失败") from None
        self.ws = ws
        self.current_transport = "websocket"
        self.state = "connected"
        engineio.client.connected_clients.append(self)
        self._trigger_event("connect", run_async=False)
        self.ping_loop_task = self.start_background_task(self._ping_loop)
        self.write_loop_task = self.start_background_task(self._write_loop)
        self.read_loop_task = self.start_background_task(self._read_loop_websocket)
        return True


class OrderedSocketClient(socketio.Client):
    observer = None

    def _engineio_client_class(self):
        return OrderedEngineClient

    def _handle_event(self, namespace, event_id, data):
        if self.observer is not None and data:
            self.observer(namespace, data[0], data[1] if len(data) > 1 else {})
        return super()._handle_event(namespace, event_id, data)


def make_client(connection: ConnectionConfig) -> OrderedSocketClient:
    logger = _quiet_logger()
    client = OrderedSocketClient(reconnection=False, logger=logger, engineio_logger=logger,
                                 request_timeout=connection.connect_timeout)
    client.eio.ws_factory = lambda url, **kwargs: create_connection(
        url, **kwargs, proxy_url=connection.proxy_url, compression=connection.compression,
        connect_timeout=connection.connect_timeout)
    return client


def connect_client(client: OrderedSocketClient, connection: ConnectionConfig) -> None:
    # EIO constructs query/path itself. Strip old explicit EIO/transport query to avoid duplicates.
    parts = urlsplit(connection.url)
    base = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
    # Legacy socketio.Client.connect used its default socket.io path even when
    # CONTROL_URL ended in '/?EIO=3&transport=websocket'. Preserve that behavior.
    path = getattr(connection, "socketio_path", None) or parts.path.strip("/") or "socket.io"
    client.connect(base, transports=["websocket"], namespaces=[connection.namespace],
                   socketio_path=path)


class LiveEventSource:
    def __init__(self, connection: ConnectionConfig, identity: IdentityConfig, *, queue_size: int = 4096):
        self.connection, self.identity = connection, identity
        self.stop = Event()
        self.queue: Queue = Queue(queue_size)
        self.client = None
        self.error: str | None = None
        self.generation = self.sequence = 0
        self._worker = None

    def _observe(self, namespace: str, name: str, data: object) -> None:
        if namespace != self.connection.namespace or not name.startswith("response:gvg_"):
            return
        self.sequence += 1
        try:
            event = decode_event(name, data, self.sequence, time.time(), self.generation)
            self.queue.put_nowait(event)
        except Full:
            self.error = "接收队列已满，会话状态不完整"
            self.stop.set()
        except ValueError:
            self.error = "接收事件解析失败，会话状态不完整"
            self.stop.set()

    def _receive(self) -> None:
        while not self.stop.is_set():
            self.generation += 1
            client = self.client = make_client(self.connection)
            client.observer = self._observe
            @client.on("connect", namespace=self.connection.namespace)
            def joined():
                client.emit("room_join", join_packet(self.connection, self.identity),
                            namespace=self.connection.namespace)
            try:
                connect_client(client, self.connection)
                while not self.stop.wait(.1) and client.connected:
                    pass
            except Exception:
                logging.getLogger("lilyrex.transport").warning("观战连接失败，等待重连")
            finally:
                try:
                    client.disconnect()
                except Exception:
                    pass
            if not self.stop.is_set():
                self.stop.wait(5)

    def events(self) -> Iterator[BattleEvent]:
        if self._worker is not None:
            raise ValueError("LiveEventSource只能消费一次")
        self._worker = Thread(target=self._receive, daemon=True, name="gvg-receiver")
        self._worker.start()
        try:
            while not self.stop.is_set() or not self.queue.empty():
                try:
                    yield self.queue.get(timeout=.1)
                except Empty:
                    pass
            if self.error:
                raise RuntimeError(self.error)
        finally:
            self.close()

    def close(self) -> None:
        self.stop.set()
        if self.client is not None:
            try:
                self.client.disconnect()
            except Exception:
                pass
        if self._worker is not None:
            self._worker.join(timeout=3)
