"""Attribute-specific damage configuration and environment precedence."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field, fields
from functools import lru_cache
import logging
import math
import os
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping
import tomllib

from lilyrex.domain.attributes import ATTRIBUTE_NAMES, AttributeValues
from lilyrex.domain.models import EstimateSettings
from .document import _error, _table, read_document

PARAMETERS = tuple(f.name for f in fields(EstimateSettings))
ATTRIBUTE_PARAMETERS = ('theme', 'charm_bonus')
POSITIVE_PARAMETERS = ('skill_level', 'benefit', 'adx', 'theme', 'costume_match_multiplier')


@dataclass(frozen=True)
class PreviewConfig:
    enabled: bool = True
    hover_delay_ms: int = 180
    defaults: EstimateSettings = field(default_factory=EstimateSettings)
    players: Mapping[int, EstimateSettings] = field(default_factory=dict)

    def settings_for(self, user_id: int) -> EstimateSettings:
        return self.players.get(user_id, self.defaults)


def _attribute_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, AttributeValues):
        return asdict(value)
    if isinstance(value, dict):
        return dict(value)
    return dict.fromkeys(ATTRIBUTE_NAMES, value)


def _overlay(values: Mapping[str, Any], layer: Mapping[str, Any], path: Path,
             prefix: str) -> dict[str, Any]:
    if set(layer) - set(PARAMETERS):
        raise _error(path, prefix + '.<unknown>')
    result = dict(values)
    for name, value in layer.items():
        result[name] = (_attribute_dict(result[name]) | value
                        if name in ATTRIBUTE_PARAMETERS and isinstance(value, dict) else value)
    return result


def _number(value: Any, path: Path, key: str, *, positive: bool = False,
            probability: bool = False) -> float:
    try:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError
        value = float(value)
        if not math.isfinite(value) or value < 0 or (positive and value == 0):
            raise ValueError
        if probability and value > 1:
            raise ValueError
        return value
    except (ValueError, OverflowError):
        raise _error(path, key) from None


def _settings(raw: Mapping[str, Any], base: EstimateSettings, path: Path,
              prefix: str) -> EstimateSettings:
    values = _overlay({name: getattr(base, name) for name in PARAMETERS}, raw, path, prefix)
    for name, value in values.items():
        key = f'{prefix}.{name}'
        if name in ATTRIBUTE_PARAMETERS:
            attrs = _attribute_dict(value)
            if set(attrs) - set(ATTRIBUTE_NAMES):
                raise _error(path, key + '.<unknown>')
            values[name] = AttributeValues(**{attr: _number(attrs[attr], path, key + '.' + attr,
                positive=name == 'theme') for attr in ATTRIBUTE_NAMES})
        else:
            values[name] = _number(value, path, key, positive=name in POSITIVE_PARAMETERS,
                                   probability=name in ('crit_rate', 'charge_fraction'))
    return EstimateSettings(**values)


def _environment(path: Path) -> dict[str, Any]:
    env = {}
    for name in PARAMETERS:
        key = f'LILYREX_DAMAGE_{name.upper()}'
        if key in os.environ:
            try:
                text = os.environ[key]
                env[name] = (tomllib.loads('value=' + text)['value']
                             if name in ATTRIBUTE_PARAMETERS and text.lstrip().startswith('{')
                             else float(text))
            except (ValueError, KeyError, OverflowError):
                raise _error(path, key) from None
    for name in ATTRIBUTE_PARAMETERS:
        attrs = {}
        for attr in ATTRIBUTE_NAMES:
            key = f'LILYREX_DAMAGE_{name.upper()}_{attr.upper()}'
            if key in os.environ:
                try:
                    attrs[attr] = float(os.environ[key])
                except ValueError:
                    raise _error(path, key) from None
        if attrs:
            env[name] = (_attribute_dict(env[name]) | attrs if name in env else attrs)
    return env


@lru_cache(maxsize=1)
def _warn_charge_fraction() -> None:
    logging.getLogger('lilyrex.config').warning(
        'charge_fraction已弃用：蓄力按比赛经过时间和各技能成长参数自动计算')


def load_config(path: Path) -> PreviewConfig:
    """Parse damage settings; explicit environment values override every player."""
    path = Path(path)
    document = read_document(path)
    raw = _table(document.get('damage_preview', {}), path, 'damage_preview')
    if set(raw) - {'enabled', 'hover_delay_ms', 'defaults', 'players'}:
        raise _error(path, 'damage_preview.<unknown>')
    enabled = raw.get('enabled', True)
    delay = raw.get('hover_delay_ms', 180)
    if 'LILYREX_PREVIEW_ENABLED' in os.environ:
        value = os.environ['LILYREX_PREVIEW_ENABLED'].lower()
        if value not in ('true', 'false', '1', '0'):
            raise _error(path, 'LILYREX_PREVIEW_ENABLED')
        enabled = value in ('true', '1')
    if 'LILYREX_PREVIEW_HOVER_DELAY_MS' in os.environ:
        try:
            delay = int(os.environ['LILYREX_PREVIEW_HOVER_DELAY_MS'])
        except ValueError:
            raise _error(path, 'LILYREX_PREVIEW_HOVER_DELAY_MS') from None
    if not isinstance(enabled, bool):
        raise _error(path, 'damage_preview.enabled')
    if type(delay) is not int or not 0 <= delay <= 5000:
        raise _error(path, 'damage_preview.hover_delay_ms')
    defaults = _table(raw.get('defaults', {}), path, 'damage_preview.defaults')
    env = _environment(path)
    _settings(env, EstimateSettings(), path, 'LILYREX_DAMAGE')
    baseline = {name: getattr(EstimateSettings(), name) for name in PARAMETERS}
    merged = _overlay(_overlay(baseline, defaults, path, 'damage_preview.defaults'),
                      env, path, 'LILYREX_DAMAGE')
    base = _settings(merged, EstimateSettings(), path, 'damage_preview.defaults')
    players: dict[int, EstimateSettings] = {}
    tables = _table(raw.get('players', {}), path, 'damage_preview.players')
    deprecated = 'charge_fraction' in defaults or 'charge_fraction' in env
    for key, value in tables.items():
        if not key.isdecimal() or int(key) <= 0:
            raise _error(path, 'damage_preview.players.<user_id>')
        uid = int(key)
        if uid in players:
            raise _error(path, 'damage_preview.players.<duplicate_user_id>')
        table = _table(value, path, 'damage_preview.players.<user_id>')
        merged = _overlay({name: getattr(base, name) for name in PARAMETERS}, table,
                          path, 'damage_preview.players.<user_id>')
        merged = _overlay(merged, env, path, 'LILYREX_DAMAGE')
        players[uid] = _settings(merged, base, path, 'damage_preview.players.<user_id>')
        deprecated |= 'charge_fraction' in table
    if deprecated:
        _warn_charge_fraction()
    return PreviewConfig(enabled, delay, base, MappingProxyType(players))
