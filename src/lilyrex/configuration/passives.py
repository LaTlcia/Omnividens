"""Passive pool configuration; no gameplay or transport dependencies."""
from __future__ import annotations
from dataclasses import fields
import math
import os
from pathlib import Path
from .document import _error, _table, read_document


def load_passive_settings(path: Path):
    """Return per-player settings callback, or None for legacy-compatible defaults."""
    from lilyrex.domain.passive_models import DeckCard, PassivePoolSettings
    document = read_document(path)
    raw = document.get('passives')
    env_names = ('mode', 'level_multiplier', 'theme_attributes', 'legendary_level')
    env = {name: os.environ[f'LILYREX_PASSIVES_{name.upper()}'] for name in env_names
           if f'LILYREX_PASSIVES_{name.upper()}' in os.environ}
    if raw is None and not env:
        return None
    raw = _table({} if raw is None else raw, path, 'passives')

    def parse(table, base=None):
        base = base or PassivePoolSettings()
        table = _table(table, path, 'passives')
        allowed = {f.name for f in fields(PassivePoolSettings)}
        if set(table) - allowed:
            raise _error(path, 'passives.<unknown>')
        values = {name: getattr(base, name) for name in allowed}
        values.update(table)
        values.update(env)
        try:
            if values['mode'] not in ('observed', 'manual', 'configured'):
                raise ValueError
            if isinstance(values['level_multiplier'], bool):
                raise ValueError
            values['level_multiplier'] = float(values['level_multiplier'])
            if not math.isfinite(values['level_multiplier']) or values['level_multiplier'] <= 0:
                raise ValueError
            if isinstance(values['legendary_level'], bool) or not isinstance(values['legendary_level'], (str, int)):
                raise ValueError
            values['legendary_level'] = int(values['legendary_level'])
            if not 0 <= values['legendary_level'] <= 5:
                raise ValueError
            attrs = values['theme_attributes']
            if isinstance(attrs, str):
                attrs = [int(x) for x in attrs.split(',') if x.strip()]
            if not isinstance(attrs, (list, tuple)) or any(type(x) is not int or x not in range(1, 6) for x in attrs):
                raise ValueError
            values['theme_attributes'] = tuple(dict.fromkeys(attrs))
            if 'deck_id' in values and values['deck_id'] is not None:
                if type(values['deck_id']) is not int or values['deck_id'] <= 0:
                    raise ValueError
            cards = []
            for card in values['cards']:
                if isinstance(card, DeckCard):
                    cards.append(card)
                    continue
                if not isinstance(card, dict) or set(card) - {f.name for f in fields(DeckCard)}:
                    raise ValueError
                item = DeckCard(**card)
                if type(item.card_id) is not int or item.card_id <= 0 or type(item.skill_id) is not int or item.skill_id < 0:
                    raise ValueError
                if item.passive_level_multiplier is not None and (
                        not math.isfinite(item.passive_level_multiplier) or item.passive_level_multiplier <= 0):
                    raise ValueError
                if item.legendary_level is not None and not 0 <= item.legendary_level <= 5:
                    raise ValueError
                cards.append(item)
            if len({c.card_id for c in cards}) != len(cards):
                raise ValueError
            values['cards'] = tuple(cards)
            if values['mode'] == 'configured' and not cards:
                raise ValueError
            return PassivePoolSettings(**values)
        except (ValueError, TypeError, OverflowError):
            raise _error(path, 'passives.settings') from None

    base = parse({k: v for k, v in raw.items() if k != 'players'})
    players = {}
    for key, value in _table(raw.get('players', {}), path, 'passives.players').items():
        if not str(key).isdecimal() or int(key) <= 0:
            raise _error(path, 'passives.players.<user_id>')
        players[int(key)] = parse(value, base)
    return lambda user_id: players.get(user_id, base)
