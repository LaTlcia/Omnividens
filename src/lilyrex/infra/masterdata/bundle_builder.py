"""Build and verify a coherent namebase and calculation bundle."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Mapping
from lilyrex.domain.masterdata import SOURCE_FILES
from lilyrex.infra.damage_catalog import LocalDamageCatalog
from .catalog_builder import FILES, build, build_passives
from .namebases import build_namebases
from .repository import NAMEBASE_FILES, load_namebases

BUNDLE_FILES = tuple(f'namebases/{name}' for name in NAMEBASE_FILES) + (
    'damage_catalog.json', 'passive_catalog.json')


def source_hashes(source_dir: Path) -> dict[str, str]:
    """Check tables and their real primary keys before invoking generators."""
    hashes = {}
    for filename in SOURCE_FILES:
        raw = (source_dir / filename).read_bytes()
        rows = json.loads(raw)['payload']['mstList']
        if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
            raise ValueError('主数据表为空或行格式无效')
        name = filename.removeprefix('masterdata_api_mst_get').removesuffix('MstList.json')
        keys = {'CardSuperAwakeningCardType': ('cardMstId', 'cardType'),
                'LegendarySkillGroup': ('legendarySkillGroupMstId', 'limitBreakCount')}.get(
                    name, (name[0].lower() + name[1:] + 'MstId',))
        unique = set()
        for row in rows:
            key = tuple(row[k] for k in keys)
            if any(type(v) is not int or v < (0 if k == 'limitBreakCount' else 1)
                   for k, v in zip(keys, key)) or key in unique:
                raise ValueError('主数据主键重复或无效')
            unique.add(key)
        hashes[filename] = hashlib.sha256(raw).hexdigest()
    return hashes


def validate_bundle(directory: Path, hashes: Mapping[str, str]) -> None:
    """Load both computation catalogs and verify their common source and IDs."""
    names = load_namebases(directory / 'namebases')
    catalog = LocalDamageCatalog(directory / 'damage_catalog.json')
    expected = {filename: hashes[filename] for filename in FILES.values()}
    if catalog.source_sha256 != expected or catalog.passive_source_sha256 != expected:
        raise ValueError('计算目录来源与版本清单不一致')
    damage = json.loads((directory / 'damage_catalog.json').read_bytes())
    passive = json.loads((directory / 'passive_catalog.json').read_bytes())
    if not damage['skills'] or not damage['orders'] or not passive['variants']:
        raise ValueError('计算目录为空')
    for row in (*damage['skills'], *passive['variants']):
        if row['card_id'] not in names['card_data'] or row['skill_id'] not in names['skill_names']:
            raise ValueError('计算条目缺少对应名称数据')


def build_bundle(source_dir: Path, out_dir: Path) -> dict[str, str]:
    """Write into a new staging directory. Publishing belongs to VersionStore."""
    try:
        hashes = source_hashes(source_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        build_namebases(source_dir, out_dir / 'namebases')
        for filename, data in (('damage_catalog.json', build(source_dir)),
                               ('passive_catalog.json', build_passives(source_dir))):
            (out_dir / filename).write_text(json.dumps(data, ensure_ascii=False,
                separators=(',', ':'), allow_nan=False) + '\n', encoding='utf-8')
        validate_bundle(out_dir, hashes)
        return hashes
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        raise ValueError('主数据构建或校验失败，未发布新版本') from None
