"""Immutable, verified data versions selected through one atomic local pointer."""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from typing import Iterator, Mapping
import uuid
from lilyrex.domain.masterdata import DatasetVersion, GENERATOR_SCHEMA, SOURCE_FILES
from .bundle_builder import BUNDLE_FILES, build_bundle, validate_bundle

_FILES = tuple(f'sources/{name}' for name in SOURCE_FILES) + BUNDLE_FILES


def _valid_revision(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{40}', value) is not None


def _write(path: Path, value: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode()


class VersionStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.versions = self.root / 'versions'
        self._pending: Path | None = None
        self._lock_stream = None
        self._verified: dict[Path, tuple[tuple, DatasetVersion]] = {}

    @contextmanager
    def lock(self) -> Iterator[bool]:
        """The persistent lock inode is never unlinked while another process waits."""
        if self._lock_stream is not None:
            yield False
            return
        if self.versions.is_symlink():
            raise ValueError('主数据版本根目录不能是符号链接')
        self.versions.mkdir(parents=True, exist_ok=True)
        lock_path = self.root / 'update.lock'
        if lock_path.is_symlink():
            raise ValueError('主数据更新锁不能是符号链接')
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        stream = os.fdopen(fd, 'r+b')
        locked = False
        try:
            if os.name == 'nt':
                import msvcrt
                if os.fstat(stream.fileno()).st_size == 0:
                    stream.write(b'\0')
                    stream.flush()
                stream.seek(0)
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    locked = True
                except OSError:
                    pass
            else:
                import fcntl
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                except BlockingIOError:
                    pass
            if locked:
                self._lock_stream = stream
            yield locked
        finally:
            if locked:
                try:
                    if os.name == 'nt':
                        stream.seek(0)
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(stream, fcntl.LOCK_UN)
                finally:
                    self._lock_stream = None
            stream.close()

    def directory(self, version: DatasetVersion) -> Path:
        if (not _valid_revision(version.revision) or type(version.generator_schema) is not int
                or version.generator_schema != GENERATOR_SCHEMA):
            raise ValueError('主数据版本标识无效')
        return self.versions / f'{version.revision}-g{version.generator_schema}'

    def _verify(self, directory: Path) -> DatasetVersion:
        if (self.versions.is_symlink() or directory.parent != self.versions or directory.is_symlink()
                or not re.fullmatch(r'[0-9a-f]{40}-g' + str(GENERATOR_SCHEMA), directory.name)):
            raise ValueError('主数据缓存目录无效')
        # Check metadata on every access, but hash/parse an unchanged version only
        # once per store. ctime also catches restoring mtime after a file edit.
        fingerprint = []
        for relative in ('manifest.json', *_FILES):
            path = directory / relative
            stat = path.lstat()
            if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
                raise ValueError('主数据缓存文件无效')
            if stat.st_size > (256 * 1024 if relative == 'manifest.json' else 64 * 1024 * 1024):
                raise ValueError('主数据缓存文件超过大小限制')
            fingerprint.append((stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
        signature = tuple(fingerprint)
        cached = self._verified.get(directory)
        if cached is not None and cached[0] == signature:
            return cached[1]
        manifest_path = directory / 'manifest.json'
        if manifest_path.is_symlink():
            raise ValueError('主数据清单无效')
        value = json.loads(manifest_path.read_bytes())
        version = DatasetVersion(value['revision'], value['generator_schema'], value['source_sha256'])
        if self.directory(version) != directory or not isinstance(version.source_sha256, dict):
            raise ValueError('主数据清单版本不一致')
        expected = value['file_sha256']
        if not isinstance(expected, dict) or set(expected) != set(_FILES):
            raise ValueError('主数据清单文件不完整')
        if set(version.source_sha256) != set(SOURCE_FILES):
            raise ValueError('主数据来源清单不完整')
        for relative, digest in expected.items():
            path = directory / relative
            if (path.is_symlink() or path.parent.is_symlink()
                    or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)
                    or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
                raise ValueError('主数据缓存完整性校验失败')
        if any(expected[f'sources/{name}'] != version.source_sha256[name] for name in SOURCE_FILES):
            raise ValueError('主数据来源哈希不一致')
        validate_bundle(directory, version.source_sha256)
        self._verified[directory] = (signature, version)
        return version

    def current(self) -> DatasetVersion | None:
        """Prefer the published pointer; recover a previous complete generation."""
        candidates = []
        try:
            pointer = self.root / 'current.json'
            if pointer.is_symlink():
                raise ValueError
            name = json.loads(pointer.read_bytes())['directory']
            if isinstance(name, str) and re.fullmatch(r'[0-9a-f]{40}-g' + str(GENERATOR_SCHEMA), name):
                candidates.append(self.versions / name)
        except (OSError, ValueError, TypeError, KeyError):
            pass
        if self.versions.is_symlink():
            return None
        if self.versions.is_dir():
            candidates.extend(sorted((p for p in self.versions.iterdir()
                if p.is_dir() and re.fullmatch(r'[0-9a-f]{40}-g' + str(GENERATOR_SCHEMA), p.name)),
                key=lambda path: path.stat().st_mtime_ns, reverse=True))
        for directory in dict.fromkeys(candidates):
            try:
                return self._verify(directory)
            except (OSError, ValueError, TypeError, KeyError):
                continue
        return None

    def prepare(self, revision: str, sources: Mapping[str, bytes]) -> DatasetVersion:
        if self._lock_stream is None:
            raise RuntimeError('准备主数据版本前必须持有更新锁')
        if not _valid_revision(revision) or set(sources) != set(SOURCE_FILES):
            raise ValueError('主数据版本或来源文件不完整')
        if any(not isinstance(raw, bytes) or not raw or len(raw) > 64 * 1024 * 1024 for raw in sources.values()):
            raise ValueError('主数据来源内容无效')
        if sum(map(len, sources.values())) > 256 * 1024 * 1024:
            raise ValueError('主数据总大小超过限制')
        self.discard_pending()
        pending = self._pending = Path(tempfile.mkdtemp(prefix='.pending-', dir=self.root))
        try:
            source_dir = pending / 'sources'
            source_dir.mkdir()
            for name in SOURCE_FILES:
                _write(source_dir / name, sources[name])
            hashes = build_bundle(source_dir, pending)
            version = DatasetVersion(revision, GENERATOR_SCHEMA, hashes)
            manifest = {**asdict(version), 'created_at_ns': time.time_ns(),
                        'file_sha256': {name: hashlib.sha256((pending / name).read_bytes()).hexdigest()
                                        for name in _FILES}}
            _write(pending / 'manifest.json', _json(manifest))
            final = self.directory(version)
            if final.exists():
                try:
                    existing = self._verify(final)
                except (OSError, ValueError, TypeError, KeyError):
                    os.replace(final, self.versions / ('.corrupt-' + uuid.uuid4().hex))
                else:
                    if existing != version:
                        raise ValueError('相同提交的主数据内容发生变化')
                    self.discard_pending()
                    return existing
            os.replace(pending, final)
            self._pending = None
            return self._verify(final)
        except Exception:
            self.discard_pending()
            raise

    def activate(self, version: DatasetVersion) -> None:
        if self._lock_stream is None:
            raise RuntimeError('发布主数据版本前必须持有更新锁')
        directory = self.directory(version)
        if self._verify(directory) != version:
            raise ValueError('主数据发布版本不一致')
        pointer = self.root / ('.current-' + uuid.uuid4().hex)
        try:
            _write(pointer, _json({'directory': directory.name}))
            os.replace(pointer, self.root / 'current.json')
        finally:
            pointer.unlink(missing_ok=True)

    def discard_pending(self) -> None:
        """Only this object's uniquely created staging path is eligible for cleanup."""
        if self._pending is not None:
            pending, self._pending = self._pending, None
            shutil.rmtree(pending)
