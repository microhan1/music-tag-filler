"""HTTP helpers shared by the search modules.

One session with the app's User-Agent, a per-host minimum interval between
requests, and retry on 429/503 with the wait reported through a callback so
the UI can show it. Only query strings and fingerprints ever leave the
machine; no audio file is uploaded anywhere.
"""
from __future__ import annotations

import threading
import time
from typing import Callable
from urllib.parse import urlsplit

import requests

APP_NAME = "music-tag-filler"
APP_VERSION = "0.1.0"
APP_URL = "https://github.com/microhan1/music-tag-filler"
USER_AGENT = f"{APP_NAME}/{APP_VERSION} ( {APP_URL} )"

TIMEOUT = 15
MAX_RETRIES = 3

WaitCallback = Callable[[float], None]


class NetworkError(Exception):
    """No connection, DNS failure, timeout: the caller should say 'offline'."""


class RateLimited(Exception):
    """Gave up after repeated 429 responses."""

    def __init__(self, wait: float) -> None:
        super().__init__(f"rate limited, wait {wait:.0f}s")
        self.wait = wait


class _Throttle:
    """Keeps at least `interval` seconds between requests to one host."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_ok: dict[str, float] = {}
        self._intervals: dict[str, float] = {}

    def set_interval(self, host: str, seconds: float) -> None:
        self._intervals[host] = seconds

    def wait(self, host: str, cancel: threading.Event | None = None) -> None:
        with self._lock:
            now = time.monotonic()
            due = self._next_ok.get(host, 0.0)
            delay = max(0.0, due - now)
            self._next_ok[host] = max(now, due) + self._intervals.get(host, 0.0)
        while delay > 0:
            if cancel is not None and cancel.is_set():
                return
            step = min(delay, 0.2)
            time.sleep(step)
            delay -= step

    def slow_down(self, host: str, seconds: float) -> None:
        """After a 429, push the next allowed time out and widen the interval a bit."""
        with self._lock:
            self._next_ok[host] = max(self._next_ok.get(host, 0.0), time.monotonic() + seconds)
            self._intervals[host] = min(10.0, self._intervals.get(host, 0.0) * 1.5 + 0.5)


throttle = _Throttle()
throttle.set_interval("itunes.apple.com", 3.1)  # ~20 requests per minute
throttle.set_interval("musicbrainz.org", 1.05)  # 1 request per second
throttle.set_interval("api.acoustid.org", 0.35)  # 3 requests per second
throttle.set_interval("coverartarchive.org", 0.5)

_session: requests.Session | None = None
_session_lock = threading.Lock()


def session() -> requests.Session:
    global _session
    with _session_lock:
        if _session is None:
            s = requests.Session()
            s.headers["User-Agent"] = USER_AGENT
            s.headers["Accept"] = "application/json, image/*;q=0.8, */*;q=0.5"
            _session = s
        return _session


def _host(url: str) -> str:
    return urlsplit(url).netloc.lower()


def request(method: str, url: str, *, params: dict | None = None, data: dict | None = None,
            on_wait: WaitCallback | None = None, cancel: threading.Event | None = None,
            stream: bool = False) -> requests.Response:
    """GET/POST with throttling and 429/503 retry. Raises NetworkError or RateLimited."""
    host = _host(url)
    last_wait = 0.0
    for attempt in range(MAX_RETRIES + 1):
        if cancel is not None and cancel.is_set():
            raise NetworkError("cancelled")
        throttle.wait(host, cancel)
        try:
            resp = session().request(method, url, params=params, data=data, timeout=TIMEOUT, stream=stream)
        except requests.RequestException as exc:
            raise NetworkError(str(exc)) from exc
        if resp.status_code in (429, 503) and attempt < MAX_RETRIES:
            wait = _retry_after(resp, default=2.0 * (attempt + 1))
            last_wait = wait
            throttle.slow_down(host, wait)
            if on_wait is not None:
                on_wait(wait)
            _sleep(wait, cancel)
            continue
        if resp.status_code in (429, 503):
            raise RateLimited(last_wait or 5.0)
        return resp
    raise RateLimited(last_wait or 5.0)  # pragma: no cover - loop always returns or raises


def get_json(url: str, params: dict | None = None, *, on_wait: WaitCallback | None = None,
             cancel: threading.Event | None = None) -> dict:
    resp = request("GET", url, params=params, on_wait=on_wait, cancel=cancel)
    if resp.status_code >= 400:
        raise NetworkError(f"HTTP {resp.status_code}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise NetworkError("bad json") from exc
    return data if isinstance(data, dict) else {}


def get_bytes(url: str, *, max_bytes: int = 20 * 1024 * 1024, on_wait: WaitCallback | None = None,
              cancel: threading.Event | None = None) -> bytes | None:
    """Download a small binary (cover art). None on 404 or when too large."""
    resp = request("GET", url, on_wait=on_wait, cancel=cancel, stream=True)
    if resp.status_code != 200:
        resp.close()
        return None
    chunks: list[bytes] = []
    total = 0
    for chunk in resp.iter_content(64 * 1024):
        if cancel is not None and cancel.is_set():
            resp.close()
            return None
        total += len(chunk)
        if total > max_bytes:
            resp.close()
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def online(timeout: float = 4.0) -> bool:
    """Cheap connectivity probe against a search host (HEAD, no throttle)."""
    for url in ("https://itunes.apple.com/", "https://musicbrainz.org/"):
        try:
            session().head(url, timeout=timeout, allow_redirects=False)
            return True
        except requests.RequestException:
            continue
    return False


def _retry_after(resp: requests.Response, default: float) -> float:
    value = resp.headers.get("Retry-After")
    if value:
        try:
            return min(60.0, max(0.5, float(value)))
        except ValueError:
            pass
    return default


def _sleep(seconds: float, cancel: threading.Event | None) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cancel is not None and cancel.is_set():
            return
        time.sleep(min(0.2, end - time.monotonic()))
