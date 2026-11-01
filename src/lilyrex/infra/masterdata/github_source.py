"""Bounded, read-only access to a pinned GitHub masterdata revision."""
from __future__ import annotations
import json
from http.client import HTTPException
import math
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from lilyrex.domain.masterdata import SOURCE_FILES


class MasterdataDownloadError(RuntimeError):
    """Public error text never includes a response body or proxy credentials."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


class GitHubMasterdataSource:
    def __init__(self, owner: str = 'LaTlcia', repository: str = 'A.RA.YA',
                 branch: str = 'main', subdirectory: str = 'MasterdataBase', *,
                 api_base: str = 'https://api.github.com',
                 raw_base: str = 'https://raw.githubusercontent.com',
                 max_file_bytes: int = 64 * 1024 * 1024):
        for value in (owner, repository):
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', value) or value in ('.', '..'):
                raise ValueError('主数据仓库名称无效')
        for value in (branch, subdirectory):
            if (not isinstance(value, str) or not value or '\\' in value or value.startswith('/')
                    or any(part in ('', '.', '..') for part in value.split('/'))
                    or any(ord(c) < 32 for c in value)):
                raise ValueError('主数据分支或目录无效')
        for base, host in ((api_base, 'api.github.com'), (raw_base, 'raw.githubusercontent.com')):
            parsed = urlsplit(base)
            local = parsed.hostname == '127.0.0.1' and parsed.scheme == 'http'
            if (not local and (parsed.scheme != 'https' or parsed.hostname != host)
                    or parsed.username or parsed.password or parsed.query or parsed.fragment
                    or parsed.path not in ('', '/')):
                raise ValueError('主数据源地址无效')
        if type(max_file_bytes) is not int or max_file_bytes <= 0:
            raise ValueError('主数据大小限制无效')
        self.owner, self.repository, self.branch, self.subdirectory = owner, repository, branch, subdirectory
        self.api_base, self.raw_base = api_base.rstrip('/'), raw_base.rstrip('/')
        self.max_file_bytes = max_file_bytes

    def _get(self, url: str, *, timeout: float, limit: int) -> bytes:
        if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('主数据请求时限必须为有限正数')
        deadline = time.monotonic() + timeout
        request = Request(url, headers={'User-Agent': 'lilyrex-masterdata/1',
                                       'Accept': 'application/json', 'Accept-Encoding': 'identity'})
        try:
            # No authentication headers are supplied; environment proxy support is
            # urllib's standard policy, independent of game connection settings.
            with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
                length = response.headers.get('Content-Length')
                expected = int(length) if length is not None else None
                if expected is not None and (expected < 0 or expected > limit):
                    raise MasterdataDownloadError('主数据响应超过大小限制')
                parts, size = [], 0
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError
                    sock = getattr(getattr(getattr(response, 'fp', None), 'raw', None), '_sock', None)
                    if sock is not None:
                        sock.settimeout(remaining)
                    chunk = response.read1(min(65536, limit - size + 1))
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > limit:
                        raise MasterdataDownloadError('主数据响应超过大小限制')
                    parts.append(chunk)
                if expected is not None and size != expected:
                    raise MasterdataDownloadError('主数据响应不完整')
                return b''.join(parts)
        except HTTPError as exc:
            exc.close()
            raise MasterdataDownloadError(f'主数据HTTP请求失败（{exc.code}）') from None
        except (URLError, OSError, ValueError, TimeoutError, HTTPException):
            raise MasterdataDownloadError('主数据请求失败或超时') from None

    def latest_revision(self, *, timeout: float) -> str:
        query = urlencode({'path': self.subdirectory, 'sha': self.branch, 'per_page': 1})
        url = f'{self.api_base}/repos/{self.owner}/{self.repository}/commits?{query}'
        try:
            rows = json.loads(self._get(url, timeout=timeout, limit=1024 * 1024))
            revision = rows[0]['sha']
            if not isinstance(revision, str) or not re.fullmatch(r'[0-9a-f]{40}', revision):
                raise ValueError
            return revision
        except (ValueError, TypeError, KeyError, IndexError):
            raise MasterdataDownloadError('主数据版本响应无效') from None

    def download(self, revision: str, filename: str, *, timeout: float) -> bytes:
        if not isinstance(revision, str) or not re.fullmatch(r'[0-9a-f]{40}', revision) or filename not in SOURCE_FILES:
            raise ValueError('主数据版本或文件名无效')
        path = '/'.join(quote(part, safe='') for part in self.subdirectory.split('/'))
        url = f'{self.raw_base}/{self.owner}/{self.repository}/{revision}/{path}/{filename}'
        return self._get(url, timeout=timeout, limit=self.max_file_bytes)
