"""Version update orchestration with injected remote and storage ports."""
from __future__ import annotations
import math
import re
import time
from typing import Callable
from lilyrex.domain.masterdata import (GENERATOR_SCHEMA, SOURCE_FILES, DatasetStore,
                                      DatasetVersion, MasterdataRemote, UpdateResult)


def refresh_masterdata(remote: MasterdataRemote, store: DatasetStore, *, enabled: bool = True,
                       check_timeout: float = 3.0, download_timeout: float = 15.0,
                       total_timeout: float = 60.0, clock: Callable[[], float] = time.monotonic,
                       progress: Callable[[str], None] | None = None) -> UpdateResult:
    """Never publish a partial dataset or leak upstream exception contents.

    Offline operation reads only a validated cached version. Every online launch
    checks the revision, while unchanged versions avoid all source downloads.
    """
    for value in (check_timeout, download_timeout, total_timeout):
        if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            raise ValueError('主数据更新超时必须为有限正数')
    notify = progress or (lambda _: None)
    deadline = clock() + total_timeout

    def current() -> DatasetVersion | None:
        try:
            return store.current()
        except Exception:
            return None

    baseline = current()
    if not enabled:
        return UpdateResult('offline', baseline, '已跳过在线更新，使用本机数据')

    def remaining(limit: float) -> float:
        budget = deadline - clock()
        if budget <= 0:
            raise TimeoutError('主数据更新超时')
        return min(limit, budget)

    def fallback(stage: str) -> UpdateResult:
        used = f'缓存 {baseline.revision[:12]}' if baseline else '内置数据'
        return UpdateResult('fallback', baseline, f'主数据{stage}失败，使用{used}')

    stage = '本机锁定'
    try:
        with store.lock() as acquired:
            if not acquired:
                return UpdateResult('fallback', baseline, '另一个进程正在更新，使用本机数据')
            # A competing process may have activated a complete version meanwhile.
            baseline = current()
            try:
                stage = '版本检查'
                notify('正在检查主数据版本…')
                revision = remote.latest_revision(timeout=remaining(check_timeout))
                if not isinstance(revision, str) or not re.fullmatch(r'[0-9a-f]{40}', revision):
                    raise ValueError('上游版本号无效')
                if (baseline is not None and baseline.revision == revision
                        and baseline.generator_schema == GENERATOR_SCHEMA):
                    return UpdateResult('unchanged', baseline, f'主数据已是最新版本 {revision[:12]}')
                stage = '下载'
                sources: dict[str, bytes] = {}
                total_bytes = 0
                for index, filename in enumerate(SOURCE_FILES, 1):
                    notify(f'正在更新主数据 {index}/{len(SOURCE_FILES)}…')
                    raw = remote.download(revision, filename, timeout=remaining(download_timeout))
                    if not isinstance(raw, bytes) or not raw or len(raw) > 64 * 1024 * 1024:
                        raise ValueError('主数据响应大小无效')
                    total_bytes += len(raw)
                    if total_bytes > 256 * 1024 * 1024:
                        raise ValueError('主数据总量超限')
                    sources[filename] = raw
                remaining(total_timeout)
                stage = '构建校验'
                notify('正在校验名称与计算数据…')
                prepared = store.prepare(revision, sources)
                if prepared.revision != revision or prepared.generator_schema != GENERATOR_SCHEMA:
                    raise ValueError('生成数据版本不一致')
                remaining(total_timeout)
                stage = '本机切换'
                store.activate(prepared)
                return UpdateResult('updated', prepared, f'主数据已更新到 {revision[:12]}')
            except Exception:
                # This adapter owns only its own pending paths, never another writer's.
                try:
                    store.discard_pending()
                except Exception:
                    pass
                return fallback(stage)
    except Exception:
        return fallback(stage)
