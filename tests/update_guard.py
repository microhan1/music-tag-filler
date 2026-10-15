"""Keep tests from reaching the real update server (chaekgalpi.co.kr).

A sibling tool's GUI tests created the App again and again; 1.5 s later each one asked the
production server, and 511 test runs were counted there as people starting the tool. The
update check's network calls are bound as default arguments
(`fetch(..., opener=urllib.request.urlopen)`, `check_async(..., fetcher=fetch)`), so replacing
`update_check.fetch` does not stop them: the defaults themselves, and `urllib.request.urlopen`,
have to be replaced. Used by tests/conftest.py (every test) and by tests that start the App in
a child process, where conftest does not reach.
"""
from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request

HOST = "chaekgalpi.co.kr"


def is_update_server(url: str) -> bool:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return host == HOST or host.endswith("." + HOST)


def make_opener(real=None):
    """An urlopen stand-in: a request to the update server is recorded in `.calls` and fails
    with URLError (what the app treats as "offline"); anything else goes to `real`."""
    real = real or urllib.request.urlopen
    calls: list[str] = []

    def guarded_urlopen(req, *args, **kwargs):
        url = getattr(req, "full_url", None) or str(req)
        if is_update_server(url):
            calls.append(url)
            raise urllib.error.URLError(f"update server blocked in tests: {url}")
        return real(req, *args, **kwargs)

    guarded_urlopen.calls = calls
    guarded_urlopen.is_update_guard = True
    return guarded_urlopen


def no_answer(slug, version):
    """Default fetcher during tests: as if offline. Tests that need an answer pass fetcher=."""
    return None


def install(update_check, opener, *, fake_fetcher: bool = True) -> None:
    """Plain install for a child process (no undo needed: the process ends)."""
    urllib.request.urlopen = opener
    update_check.fetch.__kwdefaults__["opener"] = opener
    if fake_fetcher:
        update_check.check_async.__kwdefaults__["fetcher"] = no_answer
