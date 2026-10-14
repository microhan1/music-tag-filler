"""Once a day after start: ask the 책갈피 tools site whether a newer version exists.

Only the tool's slug, its version and "win" are sent - no file, path, device or user
information. The request runs on a background thread 1.5 s after the window is shown and
never blocks the UI; any failure (offline, timeout, HTTP error, bad JSON) is silent. The
server decides whether the version is older (`updateAvailable`); null means "cannot
compare" and shows nothing. Standard library only.
"""
from __future__ import annotations

import dataclasses
import datetime
import json
import threading
import time
import urllib.parse
import urllib.request
from typing import Callable

API = "https://chaekgalpi.co.kr/api/tools/{slug}/latest"
SITE = "https://chaekgalpi.co.kr/"  # the notice only ever opens a page on this site
TIMEOUT = 4.0
DELAY_MS = 1500
MAX_BYTES = 64 * 1024
POLL_MS = 100  # the Tk thread looks for the worker's result this often
POLL_GRACE = 6.0  # beyond the request timeout before the Tk thread stops looking


@dataclasses.dataclass
class UpdateInfo:
    latest: str
    current: str
    url: str  # the tool's page (Korean)
    url_en: str = ""  # the English page when the server gives one on the tools site, else ""


def today() -> str:
    return datetime.date.today().isoformat()


def should_check(prefs, day: str) -> bool:
    """Checking is on and has not been done today."""
    return bool(getattr(prefs, "update_check", True)) and getattr(prefs, "update_check_last", "") != day


def fetch(slug: str, version: str, *, opener: Callable = urllib.request.urlopen) -> dict | None:
    """The server's answer, or None on any failure."""
    query = urllib.parse.urlencode({"v": version, "os": "win"})
    req = urllib.request.Request(f"{API.format(slug=slug)}?{query}",
                                 headers={"User-Agent": f"chaekgalpi-tool/{slug}/{version}",
                                          "Accept": "application/json"})
    try:
        with opener(req, timeout=TIMEOUT) as resp:
            if getattr(resp, "status", 200) != 200:
                return None
            data = json.loads(resp.read(MAX_BYTES).decode("utf-8"))
    except Exception:  # offline, timeout, HTTP error, bad JSON: say nothing
        return None
    return data if isinstance(data, dict) else None


def interpret(data: dict | None, version: str, skipped: str = "") -> UpdateInfo | None:
    """An UpdateInfo only when the server says a newer version exists, it is not the
    version the user chose to skip, and the link points at the tools site."""
    if not isinstance(data, dict) or data.get("updateAvailable") is not True:
        return None
    latest, url = data.get("latest"), data.get("url")
    if not isinstance(latest, str) or not latest.strip() or len(latest) > 32:
        return None
    if not isinstance(url, str) or not url.startswith(SITE):
        return None
    latest = latest.strip()
    if latest == (skipped or "").strip():
        return None
    url_en = data.get("urlEn")
    url_en = url_en if isinstance(url_en, str) and url_en.startswith(SITE) else ""
    return UpdateInfo(latest, version, url, url_en)


def link_for(info: UpdateInfo, lang: str) -> str:
    """The page [Update] opens: the Korean page on a Korean screen, the English page on any
    other screen when the server gave one on the tools site, otherwise the Korean page."""
    if lang != "ko" and info.url_en.startswith(SITE):
        return info.url_en
    return info.url


def _work(box: dict, fetcher: Callable, slug: str, version: str, skipped: str) -> None:
    """Background thread. It only fills `box`: no Tk object, no callback, nothing that
    reaches the window. If the window is closed while the request waits, this thread must
    not hold the last reference to anything Tk - releasing a Tk variable on a thread other
    than Tk's kills the process ("Tcl_AsyncDelete: async handler deleted by the wrong
    thread", reproduced in a sibling tool built the same way)."""
    try:
        data = fetcher(slug, version)
        box["result"] = (interpret(data, version, skipped), data is not None)
    except Exception:
        box["result"] = (None, False)


def check_async(root, slug: str, version: str, prefs, on_result: Callable[[UpdateInfo | None, bool], None], *,
                fetcher: Callable = fetch, day: str | None = None) -> bool:
    """Schedule one check DELAY_MS after now. on_result(info, answered) runs on the Tk
    thread: `answered` is True when the server replied (the caller records the day then),
    `info` is set only when a notice should be shown. Returns False when no check is due.
    The Tk thread polls for the worker's result; the worker never touches Tk."""
    if not should_check(prefs, day or today()):
        return False
    skipped = getattr(prefs, "update_check_skipped", "")
    box: dict = {}
    deadline = [0.0]

    def poll() -> None:
        if "result" in box:
            on_result(*box.pop("result"))
            return
        if time.monotonic() > deadline[0]:
            return  # the request outlived its timeout: give up quietly
        try:
            root.after(POLL_MS, poll)
        except Exception:  # the window is gone
            pass

    def start() -> None:
        deadline[0] = time.monotonic() + TIMEOUT + POLL_GRACE
        threading.Thread(target=_work, args=(box, fetcher, slug, version, skipped),
                         name="update-check", daemon=True).start()
        poll()

    try:
        root.after(DELAY_MS, start)
    except Exception:
        return False
    return True
