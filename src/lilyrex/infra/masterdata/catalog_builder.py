"""Compile exact card/skill pairs and supported Order coefficients."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from lilyrex.domain.charge import charge_bonus
from lilyrex.domain.masterdata import GENERATOR_SCHEMA
from lilyrex.domain.models import DamageSkill, OrderEffect

FILES = {name: f"masterdata_api_mst_get{name}MstList.json" for name in
         ("Card", "Skill", "CardSuperAwakeningCardType", "TacticsEffect", "LegendarySkillGroup", "Tactics")}


def parameters(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("parameterText") or {}
    return json.loads(value) if isinstance(value, str) else value


def _element_skill(value: Any) -> tuple[tuple[int, ...], float, bool, float, tuple[str, ...]]:
    """Preserve the previous-card condition separately from its three effects."""
    if not isinstance(value, dict):
        raise ValueError('Invalid ELEMENT_SKILL object')
    if not value:
        return (), 1.0, False, 1.0, ()
    attributes = value.get('ELEMENT_ATTRIBUTES')
    if (not isinstance(attributes, list) or not attributes
            or any(type(item) is not int or not 1 <= item <= 5 for item in attributes)
            or len(attributes) != len(set(attributes))):
        raise ValueError('Invalid ELEMENT_ATTRIBUTES')

    def number(key: str, default: float) -> float:
        raw = value.get(key, default)
        if (isinstance(raw, bool) or not isinstance(raw, (int, float))
                or not math.isfinite(raw) or raw < 0):
            raise ValueError(f'Invalid element coefficient: {key}')
        return float(raw)

    eh = 1 + number('ELEMENT_ADD_MAGNIFICATION', 0)
    sp = number('ELEMENT_USE_SP', 1)
    if not math.isfinite(eh) or not 0 < sp <= 1:
        raise ValueError('Invalid element multiplier')
    spread = value.get('ELEMENT_ADD_TARGET_NUM', 0)
    if type(spread) is not int or spread < 0:
        raise ValueError('Invalid ELEMENT_ADD_TARGET_NUM')
    known = {'ELEMENT_ATTRIBUTES', 'ELEMENT_ADD_MAGNIFICATION', 'ELEMENT_ADD_TARGET_NUM', 'ELEMENT_USE_SP'}
    unsupported = tuple(f'特殊属性技能参数未计入：{key}' for key in value if key not in known)
    return tuple(attributes), eh, spread > 0, sp, unsupported


def damage_skill(card: dict[str, Any], skill: dict[str, Any], card_type: int) -> DamageSkill:
    p = parameters(skill)
    minimum = p.get("TIME_EFFECT_MIN_SKILL_EFFECT_VALUE", 0.0)
    maximum = p.get("TIME_EFFECT_MAX_SKILL_EFFECT_VALUE", 0.0)
    interval = p.get("TIME_EFFECT_INTERVAL_SECOND", 60)
    full = p.get("TIME_EFFECT_MAX_VALUE_SECOND", 600)
    charge_bonus(None, minimum=minimum, maximum=maximum, interval_seconds=interval, full_seconds=full)
    targets = p["TARGET_NUM"]
    lo, hi = (int(targets["min"]), int(targets["max"])) if isinstance(targets, dict) else (int(targets), int(targets))
    unsupported: list[str] = []
    attributes, eh, spread, sp, element_unsupported = _element_skill(p.get('ELEMENT_SKILL', {}))
    unsupported.extend(element_unsupported)
    if "TACTICS_ACTIVATED_TARGET_NUM" in p:
        unsupported.append("目标数显示原始范围，条件扩展未计入")
    known = {"ATTACK_TYPE", "ATTACK_MAGNIFICATION", "TARGET_NUM", "ELEMENT_SKILL", "STACK_SKILLS",
             "ADD_MAGNIFICATION_BY_TACTICS", "EFFECT_UP_TACTICS", "ADD_MAGNIFICATION_AT_LOSING",
             "TACTICS_ACTIVATED_TARGET_NUM", "TARGET_NUM_ADD_TACTICS_TYPE", "RECOVERY_MAGNIFICATION", "RECOVERY_SP"}
    for key in p:
        if key in known or key.startswith(("BUFFER_", "DEBUFFER_", "TIME_EFFECT_")):
            continue
        unsupported.append({"ATTACK_UP_ATTRIBUTE": "卡组属性张数加成未计入",
                            "ADD_CARD_COUNT_MAGNIFICATION": "卡组属性张数加成未计入",
                            "ATTRIBUTE_WEAK_EFFECT_SKILL_EFFECT": "属性弱化联动加成未计入",
                            "ATTRIBUTE_WEAK_EFFECT_TYPE": "属性弱化联动加成未计入"}.get(key, f"特殊技能参数未计入：{key}"))
    return DamageSkill(
        skill_id=int(skill["skillMstId"]), card_id=int(card["cardMstId"]),
        name=skill["name"], card_name=card["name"], attribute=int(card["attribute"]),
        card_type=card_type, attack_type="physical" if p["ATTACK_TYPE"] == 1 else "magical",
        magnification=float(p["ATTACK_MAGNIFICATION"]), min_targets=lo, max_targets=hi,
        add_magnification=float(p.get("ADD_MAGNIFICATION_BY_TACTICS", 0)),
        tactics_types=tuple(int(x) for x in p.get("EFFECT_UP_TACTICS", [])),
        max_charge_bonus=maximum, min_charge_bonus=minimum,
        charge_interval_seconds=interval, charge_full_seconds=full,
        eh_multiplier=eh, ct_multiplier=1 + float(p.get("ADD_MAGNIFICATION_AT_LOSING", 0)),
        unsupported=tuple(dict.fromkeys(unsupported)), element_attributes=attributes,
        spread_max_targets=spread, element_sp_multiplier=sp)


def order_effect(row: dict[str, Any]) -> OrderEffect:
    """Match Toolbox's tactics_effect_info; percentages remain percentage points."""
    p = parameters(row)

    def number(key: str) -> float:
        try:
            raw = p.get(key, 0)
            value = float(raw)
            if isinstance(raw, bool) or not math.isfinite(value) or value < 0:
                raise ValueError
            return value
        except (ValueError, TypeError, OverflowError):
            raise ValueError(f'Invalid Order coefficient: {key}') from None

    def integer(key: str) -> int:
        value = number(key)
        if not value.is_integer():
            raise ValueError(f'Invalid Order integer: {key}')
        return int(value)

    return OrderEffect(
        effect_id=int(row["tacticsEffectMstId"]), type=int(row.get("type", 0)),
        target_attribute=integer("targetAttribute"), second_attribute=integer("secondTargetAttribute"),
        target_card_type=integer("targetCardType"), up=number("skillEffectUpAttackRate"),
        physical_up=number("skillEffectUpPhysicalAttackRate") if "skillEffectUpPhysicalAttackRate" in p else None,
        magical_up=number("skillEffectUpMagicalAttackRate") if "skillEffectUpMagicalAttackRate" in p else None,
        up2=number("secondSkillEffectUpAttackRate"), down=number("attributeGuardRate"),
        disadvantage_up=number("attackEffectUpRateUnderDisadvantage"),
        physical_reduction=number("physicalDamageReductionRate"), magical_reduction=number("magicalDamageReductionRate"),
        passive_rate_up=number("autoSkillProbabilityUpRate"), passive_rate_down=number("autoSkillProbabilityDownRate"),
        enemy_attribute=integer("enemyTargetAttribute"), enemy_attack_up=number("enemySkillEffectUpAttackRate"),
        terminate_remaining=number("terminatedConditionRemainTime"),
        terminate_point_ratio=number("terminatedConditionGuildPointRatio"),
        preparation_override=number("overwritePreparationTime"),
        enemy_duration_override=number("enemyOverwriteEffectTime"),
        state_only=any(k in p for k in ("attackUpValue", "attackDownValue", "spRecoverRate", "effectNum")),
    )


def build(source: Path) -> dict[str, Any]:
    rows: dict[str, list[dict[str, Any]]] = {}
    hashes: dict[str, str] = {}
    for name, filename in FILES.items():
        raw = (source / filename).read_bytes()
        hashes[filename] = hashlib.sha256(raw).hexdigest()
        rows[name] = json.loads(raw)["payload"]["mstList"]
    def index(name: str, key: str) -> dict[int, dict[str, Any]]:
        result: dict[int, dict[str, Any]] = {}
        for row in rows[name]:
            ident = row[key]
            if type(ident) is not int or ident <= 0 or ident in result:
                raise ValueError(f'Invalid or duplicate {name} ID')
            result[ident] = row
        return result

    cards = index("Card", "cardMstId")
    skills = index("Skill", "skillMstId")
    index("TacticsEffect", "tacticsEffectMstId")
    pairs: dict[tuple[int, int], int] = {}

    def add(card_id: int, skill_id: int, card_type: int) -> None:
        if not skill_id or card_type not in range(1, 8):
            return
        key = (card_id, skill_id)
        if key in pairs and pairs[key] != card_type:
            raise ValueError("Ambiguous card/skill type pair")
        pairs[key] = card_type

    for cid, card in cards.items():
        add(cid, card.get("gvgSkillMstId", 0), card["cardType"])
        add(cid, card.get("awakenedGvgSkillMstId", 0), card["cardType"])
        add(cid, card.get("awakenedAddGvgSkillMstId", 0), card.get("awakenedAddCardType", 0))
    for row in rows["CardSuperAwakeningCardType"]:
        add(row["cardMstId"], row["gvgSkillMstId"], row["cardType"])
    compiled = []
    rear_types = []
    for (cid, sid), ct in sorted(pairs.items()):
        if ct >= 5:
            rear_types.append([cid, sid, ct])
            continue
        p = parameters(skills[sid])
        if p.get("ATTACK_TYPE") not in (1, 2) or "ATTACK_MAGNIFICATION" not in p:
            raise ValueError("Front card has no supported damage definition")
        compiled.append(asdict(damage_skill(cards[cid], skills[sid], ct)))
    orders = [asdict(order_effect(r)) for r in sorted(rows["TacticsEffect"], key=lambda r: r["tacticsEffectMstId"])]
    return {"schema_version": GENERATOR_SCHEMA, "source_sha256": hashes,
            "formula_reference": "ArayaToolbox/method/generate_agamotto.py",
            "skills": compiled, "rear_types": rear_types, "orders": orders}


def build_passives(source: Path) -> dict[str, Any]:
    """All active variants, including rear cards which also contribute passives."""
    import re
    rows = {name: json.loads((source / filename).read_bytes())["payload"]["mstList"]
            for name, filename in FILES.items()}
    skills = {r['skillMstId']: r for r in rows['Skill']}
    cards = {r['cardMstId']: r for r in rows['Card']}
    leg_groups: dict[int, list[dict]] = {}
    for r in rows['LegendarySkillGroup']:
        leg_groups.setdefault(r['legendarySkillGroupMstId'], []).append(r)
    variants = {}
    def add(cid, sid, auto_id, leg_id):
        if sid:
            value = (auto_id, leg_id)
            if (cid, sid) in variants and variants[cid, sid] != value:
                raise ValueError('Ambiguous active/passive association')
            variants[cid, sid] = value
    for cid, card in cards.items():
        for prefix in ('', 'awakened', 'awakenedAdd'):
            def key(s): return prefix + (s[0].upper()+s[1:] if prefix else s)
            add(cid, card.get(key('gvgSkillMstId'), 0), card.get(key('gvgAutoSkillMstId'), 0),
                card.get(key('legendarySkillGroupMstId'), 0))
    for row in rows['CardSuperAwakeningCardType']:
        add(row['cardMstId'], row['gvgSkillMstId'], row.get('gvgAutoSkillMstId', 0),
            row.get('legendarySkillGroupMstId', 0))
    outputs = []
    attributes = {'火': 1, '水': 2, '風': 3, '光': 4, '闇': 5}
    pattern = re.compile(r'([火水風光闇](?:/[火水風光闇])*)属性の(通常攻撃|特殊攻撃)[^。]*?([0-9.]+)%アップ')
    crit_pattern = re.compile(r'クリティカル発動確率[をが]([0-9.]+)%アップ')
    for (cid, sid), (aid, lid) in sorted(variants.items()):
        entries = []
        auto = skills.get(aid, {})
        params = parameters(auto)
        match = re.search(r'[Ⅰ-Ⅹ](\++)?\s*$', auto.get('name', ''))
        tier = min(2, len(match.group(1) or '')) if match else 0
        for group, kind, mag in [('ATTACK', 'damage', 'ATTACK_UP_MAGNIFICATION'),
                                 ('RECOVERY', 'heal', 'RECOVERY_UP_MAGNIFICATION'),
                                 ('BUFFER', 'support', 'BUFFER_UP_MAGNIFICATION')]:
            sub = params.get(group, {})
            if mag in sub:
                entries.append(dict(source_card_id=cid, auto_skill_id=aid, host_attribute=cards[cid]['attribute'],
                                    kind=kind, coefficient=float(sub[mag]), base_probability=(.15, .225, .30)[tier]))
        legendary = []
        for level in sorted(leg_groups.get(lid, []), key=lambda r: r['limitBreakCount']):
            effects = []
            desc = level.get('description', '')
            if 'レギオンマッチ' in level.get('name', '') + desc:
                crit_match = crit_pattern.search(desc)
                for m in pattern.finditer(desc):
                    for a in m[1].split('/'):
                        effects.append(dict(attribute=attributes[a], attack_type='physical' if m[2]=='通常攻撃' else 'magical',
                                            up=float(m[3])/100, crit=float(crit_match[1])/100 if crit_match else 0))
            legendary.append(effects)
        outputs.append(dict(card_id=cid, skill_id=sid, entries=entries, legendary=legendary))
    return dict(schema_version=1, source_sha256={f:hashlib.sha256((source/f).read_bytes()).hexdigest() for f in FILES.values()},
                variants=outputs)
