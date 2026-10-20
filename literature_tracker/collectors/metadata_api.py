"""Cached, rate-limited requests to public metadata APIs."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

import requests

from ..paths import DATA_DIR


METADATA_CACHE_DIR = DATA_DIR / "metadata_cache"
_RATE_LOCK = threading.Lock()
_LAST_REQUEST: dict[str, float] = {}


class MetadataClient:
    def __init__(self, session: requests.Session, cache_dir: Path | None = METADATA_CACHE_DIR, *, min_interval: float = 0.4) -> None:
        self.session = session
        self.cache_dir = cache_dir
        self.min_interval = min_interval

    def get(self, url: str, *, params: dict, cache_ttl: int = 600) -> requests.Response:
        key = hashlib.sha256(json.dumps([url, params], sort_keys=True).encode()).hexdigest()
        cache_path = self.cache_dir / f"{key}.cache" if self.cache_dir else None
        if cache_path:
            try:
                if 0 <= time.time() - cache_path.stat().st_mtime < cache_ttl:
                    cached = requests.Response()
                    cached.status_code = 200
                    cached.url = url
                    cached._content = cache_path.read_bytes()
                    cached.encoding = "utf-8"
                    return cached
            except OSError:
                pass

        for attempt in range(3):
            self._throttle(url)
            try:
                response = self.session.get(url, params=params, timeout=20)
            except (requests.ConnectionError, requests.Timeout):
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
                continue
            if response.status_code in {429, 502, 503, 504} and attempt < 2:
                delay = self._retry_delay(response, attempt)
                # A long server cooldown must be respected by deferring this run.
                if delay > 30:
                    response.raise_for_status()
                time.sleep(delay)
                continue
            response.raise_for_status()
            if cache_path:
                self._save_cache(cache_path, response.content)
            return response
        raise RuntimeError("Metadata request did not complete")

    def _throttle(self, url: str) -> None:
        host = urlsplit(url).netloc
        with _RATE_LOCK:
            delay = self.min_interval - (time.monotonic() - _LAST_REQUEST.get(host, 0))
            if delay > 0:
                time.sleep(delay)
            _LAST_REQUEST[host] = time.monotonic()

    @staticmethod
    def _retry_delay(response: requests.Response, attempt: int) -> float:
        header = response.headers.get("Retry-After", "")
        try:
            return max(0, float(header))
        except ValueError:
            try:
                return max(0, (parsedate_to_datetime(header) - datetime.now(timezone.utc)).total_seconds())
            except (ValueError, TypeError, OverflowError):
                return float(2 ** attempt)

    @staticmethod
    def _save_cache(path: Path, content: bytes) -> None:
        temporary = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(content)
            os.replace(temporary, path)
        except OSError:
            pass
        finally:
            try:
                if temporary and temporary.exists():
                    temporary.unlink()
            except OSError:
                pass
