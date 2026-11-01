"""Application, connection, path and update settings."""
from __future__ import annotations
from dataclasses import dataclass, field, fields
from pathlib import Path
import re
from typing import Any

from .document import _error, _table, read_document, scalar_value
from .preview import PreviewConfig, load_config


@dataclass(frozen=True)
class ConnectionConfig:
    url: str = 'https://reflector-allb.assaultlily-lb.jp/?EIO=3&transport=websocket'
    room_id: str = ''
    proxy_url: str = field(default='', repr=False)
    compression: bool = True
    connect_timeout: float = 30.0
    namespace: str = '/march'
    socketio_path: str = 'socket.io'


@dataclass(frozen=True)
class IdentityConfig:
    uuid: str = field(default='', repr=False)
    user_id: int = 0
    user_name: str = ''
    user_agent: str = 'UnityRequest'
    watcher_user_id: int = 0


@dataclass(frozen=True)
class MasterdataUpdateConfig:
    enabled: bool = True
    cache_dir: Path = Path('.lilyrex/masterdata')
    owner: str = 'LaTlcia'
    repository: str = 'A.RA.YA'
    branch: str = 'main'
    subdirectory: str = 'MasterdataBase'
    check_timeout: float = 3.0
    download_timeout: float = 15.0
    total_timeout: float = 60.0


@dataclass(frozen=True)
class AppConfig:
    path: Path
    connection: ConnectionConfig
    identity: IdentityConfig
    preview: PreviewConfig
    data_dir: Path
    namebase_dir: Path | None = None
    assets_dir: Path | None = None
    log_level: str = 'INFO'
    replay_speed: float = 1.0
    replay_timing: str = 'server'
    replay_warmup: bool = True
    ui_title: str = 'GVG Battle Monitor'
    catalog_dir: Path | None = None
    masterdata_update: MasterdataUpdateConfig = field(default_factory=MasterdataUpdateConfig)

    def require_connection(self) -> None:
        for key, value in (('connection.room_id', self.connection.room_id),
                           ('identity.uuid', self.identity.uuid)):
            if not value:
                raise _error(self.path, key)


def load_app_config(path: Path) -> AppConfig:
    path = Path(path).resolve()
    document = read_document(path)

    def value(group: str, name: str, default: Any) -> Any:
        return scalar_value(document, path, group, name, default)

    conn = ConnectionConfig(**{f.name: value('connection', f.name, f.default)
                               for f in fields(ConnectionConfig)})
    if not conn.url.startswith(('https://', 'http://', 'wss://', 'ws://')) or conn.connect_timeout <= 0:
        raise _error(path, 'connection.url/connect_timeout')
    ident = IdentityConfig(**{f.name: value('identity', f.name, f.default)
                             for f in fields(IdentityConfig)})

    def relative(text: str) -> Path:
        candidate = Path(text).expanduser()
        return candidate if candidate.is_absolute() else path.parent / candidate

    def local_path(name: str, default: str = '') -> Path | None:
        text = value('paths', name, default)
        return relative(text) if text else None

    update_raw = _table(document.get('masterdata_update', {}), path, 'masterdata_update')
    if set(update_raw) - {f.name for f in fields(MasterdataUpdateConfig)}:
        raise _error(path, 'masterdata_update.<unknown>')
    update = {f.name: value('masterdata_update', f.name,
                           str(f.default) if isinstance(f.default, Path) else f.default)
              for f in fields(MasterdataUpdateConfig)}
    for key in ('owner', 'repository'):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', update[key]) or update[key] in ('.', '..'):
            raise _error(path, 'masterdata_update.' + key)
    for key in ('branch', 'subdirectory'):
        text = update[key]
        if ('\\' in text or any(ord(char) < 32 for char in text)
                or any(part in ('', '.', '..') for part in text.split('/'))):
            raise _error(path, 'masterdata_update.' + key)
    for key in ('check_timeout', 'download_timeout', 'total_timeout'):
        if update[key] <= 0:
            raise _error(path, 'masterdata_update.' + key)
    if not update['cache_dir']:
        raise _error(path, 'masterdata_update.cache_dir')
    update['cache_dir'] = relative(update['cache_dir'])

    level = value('logging', 'level', 'INFO').upper()
    if level not in ('DEBUG', 'INFO', 'WARNING', 'ERROR'):
        raise _error(path, 'logging.level')
    speed, timing = value('replay', 'speed', 1.0), value('replay', 'timing', 'server')
    if speed <= 0 or timing not in ('server', 'recorded', 'burst'):
        raise _error(path, 'replay.speed/timing')
    return AppConfig(path, conn, ident, load_config(path),
                     local_path('data_dir', 'dev_tools/data'), local_path('namebase_dir'),
                     local_path('assets_dir'), level, speed, timing,
                     value('replay', 'warmup', True), value('ui', 'title', 'GVG Battle Monitor'),
                     local_path('catalog_dir'), MasterdataUpdateConfig(**update))
