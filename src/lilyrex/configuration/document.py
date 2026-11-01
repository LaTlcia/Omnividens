"""TOML loading and typed scalar fields with redacted configuration errors."""
from __future__ import annotations
import math
import os
from pathlib import Path
from typing import Any
import tomllib


class ConfigError(ValueError):
    """Names the file and known field, never the invalid input value."""


def _error(path: Path, name: str) -> ConfigError:
    return ConfigError(f'配置错误：{path}，字段 {name}')


def _table(raw: Any, path: Path, name: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise _error(path, name)
    return raw


def read_document(path: Path) -> dict[str, Any]:
    path = Path(path)
    try:
        return tomllib.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        raise _error(path, 'TOML') from None


def scalar_value(document: dict, path: Path, group: str, name: str, default: Any) -> Any:
    table = _table(document.get(group, {}), path, group)
    raw = os.environ.get(f'LILYREX_{group.upper()}_{name.upper()}', table.get(name, default))
    try:
        if type(default) is bool:
            if isinstance(raw, str) and raw.lower() in ('true', 'false', '1', '0'):
                return raw.lower() in ('true', '1')
            if type(raw) is not bool:
                raise ValueError
        elif type(default) in (float, int):
            if isinstance(raw, bool):
                raise ValueError
            if type(default) is int and not isinstance(raw, (str, int)):
                raise ValueError
            raw = type(default)(raw)
            if not math.isfinite(raw) or raw < 0:
                raise ValueError
        elif not isinstance(raw, str):
            raise ValueError
        return raw
    except (TypeError, ValueError, OverflowError):
        raise _error(path, f'{group}.{name}') from None
