"""Build display catalogs from explicit local public masterdata."""
from __future__ import annotations
from collections import defaultdict
from pathlib import Path
import json

CARD_TYPE_MAP = {1: '通常単体', 2: '通常範囲', 3: '特殊単体', 4: '特殊範囲', 5: '支援', 6: '妨害', 7: '回復'}

def _dedup_keep_max(items, name_key, id_key):
    grouped = defaultdict(list)
    for it in items:
        grouped[it[name_key]].append(it)
    return {max(g, key=lambda x: x[id_key])[id_key]: max(g, key=lambda x: x[id_key])
            for g in grouped.values()}

def _build_cards(card_list, skill_list):
    """Only what the deck tracker shows, as flat id-keyed maps (loads in a few ms)."""
    cards = {c["cardMstId"]: [c["name"], c["attribute"], c["cardType"]] for c in card_list}
    skills = {s["skillMstId"]: s["name"] for s in skill_list}
    return cards, skills

def _build_orders(tactics_list, effect_list):
    effect_by_id = {e["tacticsEffectMstId"]: e for e in effect_list}
    for od in tactics_list:
        for key, prefix in (("gvgTacticsEffectMstId", "gvg"),
                            ("questTacticsEffectMstId", "pve")):
            eff = effect_by_id.get(od.get(key))
            if eff is not None:
                od[key] = eff["name"] + "|" + eff["description"]
                od[prefix + "sp"] = eff["sp"]
                od[prefix + "preparationTime"] = eff["preparationTime"]
                od[prefix + "effectTime"] = eff["effectTime"]
    namebase = _dedup_keep_max(tactics_list, "name", "tacticsMstId")
    return tactics_list, namebase

def _resolve_rare_skill(job, character_by_id, skill_by_id):
    if job["gvgRareSkillMstId"] == 0:
        char = character_by_id.get(job["characterMstId"])
        sk = skill_by_id.get(char["gvgRareSkillMstId"]) if char else None
    else:
        sk = skill_by_id.get(job["gvgRareSkillMstId"])
    if sk is not None:
        val = f'{sk["name"]}:{sk["description"]}'
        job["gvgRareSkillMstId"] = val
        job["questRareSkillMstId"] = val

def _resolve_bonus_weapon(job, weapon_by_id):
    bw = job["bonusWeaponMstId"]
    if bw == 0:
        job["bonusWeaponMstId"] = "无"
    else:
        w = weapon_by_id.get(bw)
        if w is not None:
            job["bonusWeaponMstId"] = w["name"]

def _resolve_support_skill(job, skill_by_id):
    sk = skill_by_id.get(job["supportSkillMstId1"])
    if sk is not None:
        job["supportSkillMstId1"] = f'{sk["name"]}:{sk["description"]}'

def _build_lvlup(job, js_by_job, js_by_group):
    jid, gid = job["characterJobMstId"], job["characterJobSkillGroupId"]
    seen, relevant = set(), []
    for idx, e in js_by_job.get(jid, ()):
        if idx not in seen:
            seen.add(idx); relevant.append((idx, e))
    if gid != 0:
        for idx, e in js_by_group.get(gid, ()):
            if idx not in seen:
                seen.add(idx); relevant.append((idx, e))
    relevant.sort(key=lambda p: p[0])  # restore global list order

    lines, cur, Lv = [], "", 0
    for _, e in relevant:
        jst = "共通:" if e["jobSkillType"] < 6 else "固有:"
        if Lv != e["level"]:
            Lv = e["level"]
            cur = f'\nLv{e["level"]}: {jst}{e["name"]}'
        else:
            if lines:
                lines.pop()
            cur += f', {jst}{e["name"]}'
        lines.append(cur)
    return "".join(lines)

def _build_special(job, ss_by_job, se_by_id):
    bucket = {}
    for ss in ss_by_job.get(str(job["characterJobMstId"]), ()):
        for se in se_by_id.get(str(ss["characterJobSpecialSkillEffectMstId"]), ()):
            lb = ss["limitBreakCount"]
            bucket.setdefault(lb, "")
            bucket[lb] += f'{se["name"]}:{se["description"]}\n'
    if not bucket:
        return "```無```"
    body = "".join(f"-----{lb}*-----\n{txt}\n" for lb, txt in bucket.items())
    return f"```{body}```"

def _build_charas(lists):
    char_jobs = lists["getCharacterJobMstList"]
    character_by_id = {c["characterMstId"]: c for c in lists["getCharacterMstList"]}
    skill_by_id = {s["skillMstId"]: s for s in lists["getSkillMstList"]}
    weapon_by_id = {w["weaponMstId"]: w for w in lists["getWeaponMstList"]}

    js_by_job, js_by_group = defaultdict(list), defaultdict(list)
    for idx, e in enumerate(lists["getCharacterJobSkillMstList"]):
        js_by_job[e["characterJobMstId"]].append((idx, e))
        js_by_group[e["characterJobSkillGroupId"]].append((idx, e))

    ss_by_job = defaultdict(list)
    for ss in lists["getCharacterJobSpecialSkillMstList"]:
        ss_by_job[str(ss["characterJobMstId"])].append(ss)
    se_by_id = defaultdict(list)
    for se in lists["getCharacterJobSpecialSkillEffectMstList"]:
        se_by_id[str(se["characterJobSpecialSkillEffectMstId"])].append(se)

    for job in char_jobs:
        _resolve_rare_skill(job, character_by_id, skill_by_id)
        job["mainCardType"] = CARD_TYPE_MAP.get(job["mainCardType"], job["mainCardType"])
        _resolve_bonus_weapon(job, weapon_by_id)
        _resolve_support_skill(job, skill_by_id)
        job["lvlupdata"] = _build_lvlup(job, js_by_job, js_by_group)
        job["characterJobSpecialSkill"] = _build_special(job, ss_by_job, se_by_id)

    namebase = _dedup_keep_max(char_jobs, "name", "characterJobMstId")
    return char_jobs, namebase

def build_namebases(source_dir: Path, out_dir: Path) -> dict[str, int]:
    """Explicit local build; missing inputs fail instead of silently networking."""
    names = ('Tactics', 'TacticsEffect', 'CharacterJob', 'Character', 'Skill',
             'Weapon', 'CharacterJobSkill', 'CharacterJobSpecialSkill',
             'CharacterJobSpecialSkillEffect', 'Card')
    lists = {}
    for name in names:
        path = Path(source_dir) / f'masterdata_api_mst_get{name}MstList.json'
        try:
            rows = json.loads(path.read_text(encoding='utf-8'))['payload']['mstList']
            primary = name[0].lower() + name[1:] + 'MstId'
            if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
                raise ValueError
            keys = [row[primary] for row in rows]
            if any(type(key) is not int or key <= 0 for key in keys) or len(keys) != len(set(keys)):
                raise ValueError
            lists[f'get{name}MstList'] = rows
        except (OSError, ValueError, KeyError, TypeError):
            raise ValueError(f'主数据读取失败：{path}') from None
    _, orders = _build_orders(lists['getTacticsMstList'], lists['getTacticsEffectMstList'])
    _, charas = _build_charas(lists)
    cards, skills = _build_cards(lists['getCardMstList'], lists['getSkillMstList'])
    outputs = {'Chara': charas, 'Order': orders, 'Card': cards, 'Skill': skills}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, value in outputs.items():
        (out_dir / f'{name}_Namebase.json').write_text(
            json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    return {name: len(value) for name, value in outputs.items()}
