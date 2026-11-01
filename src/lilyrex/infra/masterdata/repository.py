"""Read installed resources or explicitly configured local replacements."""
from __future__ import annotations
from importlib.resources import files
import json
from pathlib import Path
from typing import Any

NAMEBASE_FILES = tuple(f'{stem}_Namebase.json' for stem in ('Chara', 'Order', 'Card', 'Skill'))
CARD_TYPES = ('通常単体', '通常範囲', '特殊単体', '特殊範囲', '支援', '妨害', '回復')


def validate_namebase(stem: str, value: Any) -> None:
    if not isinstance(value, dict) or not value:
        raise ValueError('名称目录为空或格式无效')
    for key, row in value.items():
        if not isinstance(key, str) or not key.isascii() or not key.isdecimal() or int(key) <= 0:
            raise ValueError('名称目录ID无效')
        if str(int(key)) != key:
            raise ValueError('名称目录ID不是规范整数')
        if stem == 'Card':
            if (not isinstance(row, list) or len(row) != 3 or not isinstance(row[0], str)
                    or type(row[1]) is not int or row[1] not in range(1, 6)
                    or type(row[2]) is not int or row[2] not in range(1, 8)):
                raise ValueError('卡牌名称目录格式无效')
        elif stem == 'Skill':
            if not isinstance(row, str):
                raise ValueError('技能名称目录格式无效')
        elif not isinstance(row, dict) or not isinstance(row.get('name'), str):
            raise ValueError('角色或Order名称目录格式无效')
        elif stem == 'Chara' and row.get('mainCardType') not in CARD_TYPES:
            raise ValueError('角色主牌型无效')


def load_namebases(directory: Path | None = None) -> dict[str, dict]:
    base = directory or files('lilyrex').joinpath('data', 'namebases')
    result = {}
    for stem, key in (('Chara', 'chara_data'), ('Order', 'order_data'),
                      ('Card', 'card_data'), ('Skill', 'skill_names')):
        path = base.joinpath(f'{stem}_Namebase.json')
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
            validate_namebase(stem, value)
            result[key] = ({int(k): tuple(v) for k, v in value.items()} if stem == 'Card'
                           else {int(k): v for k, v in value.items()} if stem == 'Skill' else value)
        except (OSError, ValueError, TypeError):
            raise ValueError(f'主数据不可用：{path}') from None
    return result


def assets_path(override: Path | None = None) -> Path:
    path = override or Path(str(files('lilyrex').joinpath('data', 'assets')))
    if not path.is_dir():
        raise ValueError(f'图像资源目录不可用：{path}')
    return path


def job_card_types(chara_data: dict[str, Any]) -> dict[int, int]:
    names = ('通常単体', '通常範囲', '特殊単体', '特殊範囲', '支援', '妨害', '回復')
    values = {name: i + 1 for i, name in enumerate(names)}
    return {int(key): values.get(row.get('mainCardType'), 0) for key, row in chara_data.items()}
