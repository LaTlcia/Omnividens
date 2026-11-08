"""Read the packaged, public masterdata subset without importing Toolbox."""
from __future__ import annotations

from dataclasses import fields
from importlib.resources import files
import json
import math
from pathlib import Path
from typing import Any

from lilyrex.domain.charge import charge_bonus
from lilyrex.domain.models import DamageSkill, OrderEffect
from lilyrex.domain.passive_models import CardPassives, LegendaryEntry, PassiveEntry


class CatalogError(ValueError):
    """Invalid or incomplete local catalog, never a network failure."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('重复JSON字段')
        result[key] = value
    return result


def _integer(value: Any, minimum: int = 0, maximum: int | None = None) -> None:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError('整数取值无效')


def _number(value: Any, minimum: float = 0, maximum: float | None = None, *, positive: bool = False) -> None:
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            or value < minimum or (positive and value == 0) or (maximum is not None and value > maximum)):
        raise ValueError('数值取值无效')


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ValueError('文本列表无效')
    return tuple(value)


def _hashes(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or any(
        not isinstance(k, str) or not k or not isinstance(v, str) or len(v) != 64
        or any(c not in '0123456789abcdef' for c in v) for k, v in value.items()
    ):
        raise ValueError('来源摘要无效')
    return dict(value)


def _validate_skill(skill: DamageSkill) -> None:
    for value in (skill.card_id, skill.skill_id):
        _integer(value, 1)
    _integer(skill.attribute, 1, 5)
    _integer(skill.card_type, 1, 4)
    _integer(skill.min_targets, 1)
    _integer(skill.max_targets, skill.min_targets)
    if (skill.attack_type not in ('physical', 'magical') or not isinstance(skill.name, str)
            or not isinstance(skill.card_name, str)):
        raise ValueError('技能类型或名称无效')
    for value in (skill.magnification, skill.eh_multiplier, skill.ct_multiplier):
        _number(value, positive=True)
    _number(skill.add_magnification)
    for value in skill.tactics_types:
        _integer(value, 1)
    for value in skill.element_attributes:
        _integer(value, 1, 5)
    if (len(skill.element_attributes) != len(set(skill.element_attributes))
            or type(skill.spread_max_targets) is not bool):
        raise ValueError('属性条件或范围字段无效')
    _number(skill.element_sp_multiplier, positive=True, maximum=1)
    charge_bonus(None, minimum=skill.min_charge_bonus, maximum=skill.max_charge_bonus,
                 interval_seconds=skill.charge_interval_seconds, full_seconds=skill.charge_full_seconds)


def _validate_order(effect: OrderEffect) -> None:
    _integer(effect.effect_id, 1)
    for name in ('target_attribute', 'second_attribute', 'enemy_attribute'):
        _integer(getattr(effect, name), 0, 5)
    _integer(effect.type)
    _integer(effect.target_card_type, 0, 6)
    if type(effect.state_only) is not bool:
        raise ValueError('Order状态字段无效')
    excluded = {'effect_id', 'type', 'target_attribute', 'second_attribute', 'enemy_attribute',
                'target_card_type', 'unsupported', 'state_only'}
    for field in fields(effect):
        value = getattr(effect, field.name)
        if field.name in excluded or (field.name in ('physical_up', 'magical_up') and value is None):
            continue
        _number(value)


def _validate_passive(value: CardPassives) -> None:
    _integer(value.card_id, 1)
    _integer(value.skill_id, 1)
    seen: set[tuple[int, str]] = set()
    for entry in value.entries:
        _integer(entry.auto_skill_id, 1)
        _integer(entry.host_attribute, 1, 5)
        _number(entry.coefficient)
        _number(entry.base_probability, maximum=1)
        key = (entry.auto_skill_id, entry.kind)
        if (entry.source_card_id != value.card_id or type(entry.source_card_id) is not int
                or entry.kind not in ('damage', 'heal', 'support') or key in seen):
            raise ValueError('被动字段或唯一键无效')
        seen.add(key)
    for level in value.legendary:
        for entry in level:
            _integer(entry.attribute, 1, 5)
            if entry.attack_type not in ('physical', 'magical'):
                raise ValueError('传奇伤害类型无效')
            _number(entry.up)
            _number(entry.crit, maximum=1)


class LocalDamageCatalog:
    def __init__(self, path: Path | None = None) -> None:
        source = path if path is not None else files("lilyrex").joinpath("data/damage_catalog.json")
        try:
            data = json.loads(source.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
            if type(data["schema_version"]) is not int or data["schema_version"] not in (1, 2, 3, 4, 5):
                raise ValueError
            self.source_sha256 = _hashes(data["source_sha256"])
            if not isinstance(data['skills'], list) or not isinstance(data['orders'], list):
                raise ValueError
            self._skills: dict[tuple[int, int], DamageSkill] = {}
            for item in data["skills"]:
                item = dict(item)
                if data['schema_version'] >= 3 and not all(name in item for name in (
                    'min_charge_bonus', 'charge_interval_seconds', 'charge_full_seconds')):
                    raise ValueError
                if data['schema_version'] >= 4 and not all(name in item for name in (
                    'element_attributes', 'spread_max_targets', 'element_sp_multiplier')):
                    raise ValueError
                item["unsupported"] = _strings(item.get("unsupported", []))
                if not isinstance(item.get('tactics_types', []), list):
                    raise ValueError
                item["tactics_types"] = tuple(item.get("tactics_types", ()))
                if not isinstance(item.get('element_attributes', []), list):
                    raise ValueError
                item['element_attributes'] = tuple(item.get('element_attributes', ()))
                skill = DamageSkill(**item)
                _validate_skill(skill)
                if (data['schema_version'] >= 4 and not skill.element_attributes
                        and (skill.eh_multiplier != 1 or skill.spread_max_targets
                             or skill.element_sp_multiplier != 1)):
                    raise ValueError
                key = (skill.card_id, skill.skill_id)
                if key in self._skills:
                    raise ValueError
                self._skills[key] = skill
            self._card_types = {key: skill.card_type for key, skill in self._skills.items()}
            if data['schema_version'] >= 5:
                if not isinstance(data['rear_types'], list):
                    raise ValueError
                for cid, sid, card_type in data['rear_types']:
                    if (any(type(v) is not int or v <= 0 for v in (cid, sid, card_type))
                            or card_type not in (5, 6, 7) or (cid, sid) in self._card_types):
                        raise ValueError
                    self._card_types[cid, sid] = card_type
            self._orders: dict[int, OrderEffect] = {}
            for item in data["orders"]:
                item = dict(item)
                item["unsupported"] = _strings(item.get("unsupported", []))
                effect = OrderEffect(**item)
                _validate_order(effect)
                if effect.effect_id in self._orders:
                    raise ValueError
                self._orders[effect.effect_id] = effect
        except (OSError, ValueError, KeyError, TypeError, OverflowError):
            raise CatalogError(f"伤害目录缺失或格式错误：{source}") from None
        self._passives: dict[tuple[int, int], CardPassives] = {}
        self.passive_source_sha256: dict[str, str] = {}
        passive_source = path.with_name('passive_catalog.json') if path is not None else files('lilyrex').joinpath('data/passive_catalog.json')
        if passive_source.is_file():
            try:
                passive_data = json.loads(passive_source.read_text(encoding='utf-8'), object_pairs_hook=_unique_object)
                if type(passive_data['schema_version']) is not int or passive_data['schema_version'] != 1:
                    raise ValueError
                self.passive_source_sha256 = _hashes(passive_data['source_sha256'])
                if not isinstance(passive_data['variants'], list):
                    raise ValueError
                for row in passive_data['variants']:
                    if (not isinstance(row['entries'], list) or not isinstance(row['legendary'], list)
                            or any(not isinstance(level, list) for level in row['legendary'])):
                        raise ValueError
                    value = CardPassives(row['card_id'], row['skill_id'],
                        tuple(PassiveEntry(**x) for x in row['entries']),
                        tuple(tuple(LegendaryEntry(**x) for x in level) for level in row['legendary']))
                    _validate_passive(value)
                    key = (value.card_id, value.skill_id)
                    if key in self._passives:
                        raise ValueError
                    self._passives[key] = value
            except (OSError, ValueError, KeyError, TypeError, OverflowError):
                raise CatalogError(f'被动目录缺失或格式错误：{passive_source}') from None

    def card_type(self, card_id: int, skill_id: int) -> int | None:
        return self._card_types.get((card_id, skill_id))

    def skill(self, card_id: int, skill_id: int) -> DamageSkill | None:
        return self._skills.get((card_id, skill_id))

    def order(self, effect_id: int) -> OrderEffect | None:
        return self._orders.get(effect_id)

    def passives(self, card_id: int, skill_id: int) -> CardPassives | None:
        return self._passives.get((card_id, skill_id))
