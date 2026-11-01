"""Masterdata update contracts without network or filesystem implementations."""
from __future__ import annotations
from dataclasses import dataclass
from typing import ContextManager, Literal, Mapping, Protocol

GENERATOR_SCHEMA = 4
SOURCE_FILES = tuple(f'masterdata_api_mst_get{name}MstList.json' for name in (
    'Tactics', 'TacticsEffect', 'CharacterJob', 'Character', 'Skill', 'Weapon',
    'CharacterJobSkill', 'CharacterJobSpecialSkill', 'CharacterJobSpecialSkillEffect',
    'Card', 'CardSuperAwakeningCardType', 'LegendarySkillGroup'))


@dataclass(frozen=True)
class DatasetVersion:
    revision: str
    generator_schema: int
    source_sha256: Mapping[str, str]


@dataclass(frozen=True)
class UpdateResult:
    status: Literal['updated', 'unchanged', 'offline', 'fallback', 'local']
    version: DatasetVersion | None
    notice: str


class MasterdataRemote(Protocol):
    def latest_revision(self, *, timeout: float) -> str: ...
    def download(self, revision: str, filename: str, *, timeout: float) -> bytes: ...


class DatasetStore(Protocol):
    def lock(self) -> ContextManager[bool]: ...
    def current(self) -> DatasetVersion | None: ...
    def prepare(self, revision: str, sources: Mapping[str, bytes]) -> DatasetVersion: ...
    def activate(self, version: DatasetVersion) -> None: ...
    def discard_pending(self) -> None: ...
