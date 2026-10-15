"""Every test runs with the update server out of reach (see tests/update_guard.py).

- check_async's default fetcher answers "offline" (tests that want an answer pass fetcher=);
- fetch's default opener and urllib.request.urlopen refuse chaekgalpi.co.kr and record it;
- a test that tried to reach the server fails at teardown, naming the URL.

Counted before this was added (2026-10-15): 0 requests in the whole suite of 274 tests,
including the child processes of test_update_close.py.
"""
import os
import sys
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import update_check  # noqa: E402
import update_guard  # noqa: E402


@pytest.fixture(autouse=True)
def update_server_blocked(monkeypatch):
    """Yields the guard so a test can look at (and clear) what it caught."""
    opener = update_guard.make_opener(urllib.request.urlopen)
    monkeypatch.setattr(urllib.request, "urlopen", opener)
    monkeypatch.setitem(update_check.fetch.__kwdefaults__, "opener", opener)
    monkeypatch.setitem(update_check.check_async.__kwdefaults__, "fetcher", update_guard.no_answer)
    yield opener
    if opener.calls:
        pytest.fail(f"a test tried to reach the update server: {opener.calls}", pytrace=False)
