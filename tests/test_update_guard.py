"""The guard in conftest.py itself: the update server cannot be reached from a test, and a
test that tries anyway fails."""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import update_check as uc  # noqa: E402
import update_guard  # noqa: E402


def test_defaults_are_replaced(update_server_blocked):
    assert uc.fetch.__kwdefaults__["opener"] is update_server_blocked
    assert urllib.request.urlopen is update_server_blocked
    assert getattr(update_server_blocked, "is_update_guard", False)
    assert uc.check_async.__kwdefaults__["fetcher"] is update_guard.no_answer


def test_fetch_without_arguments_is_recorded_and_offline(update_server_blocked):
    assert uc.fetch("musictag", "0.0.0") is None  # the app treats this as offline: no notice
    assert len(update_server_blocked.calls) == 1
    assert "chaekgalpi.co.kr/api/tools/musictag/latest" in update_server_blocked.calls[0]
    update_server_blocked.calls.clear()  # caught on purpose: do not fail this test at teardown


def test_direct_urlopen_is_refused(update_server_blocked):
    with pytest.raises(urllib.error.URLError):
        urllib.request.urlopen("https://chaekgalpi.co.kr/api/tools/musictag/latest?v=0&os=win", timeout=1)
    with pytest.raises(urllib.error.URLError):
        urllib.request.urlopen("https://www.chaekgalpi.co.kr/x", timeout=1)  # subdomains too
    assert len(update_server_blocked.calls) == 2
    update_server_blocked.calls.clear()


def test_check_async_with_its_default_fetcher_asks_nobody(update_server_blocked):
    """What an App built in a test does 1.5 s after start: the default fetcher answers
    "offline", nothing reaches the server, and the day is not recorded."""

    class QueueRoot:  # collects after() callbacks; the test runs them like a Tk loop would
        def __init__(self):
            self.queue = []

        def after(self, ms, fn):
            self.queue.append(fn)

    import prefs as prefs_mod

    root, results = QueueRoot(), []
    assert uc.check_async(root, "musictag", "0.0.0", prefs_mod.Prefs(),
                          lambda info, answered: results.append((info, answered)), day="2026-10-15")
    deadline = time.monotonic() + 5
    while root.queue and time.monotonic() < deadline:
        root.queue.pop(0)()
        time.sleep(0.01)
    assert results == [(None, False)]
    assert update_server_blocked.calls == []


@pytest.mark.skipif(os.environ.get("MTF_GUARD_PROBE") != "1", reason="run only by the test below")
def test_probe_leaks_on_purpose():
    uc.fetch("musictag", "0.0.0")  # left recorded: the guard must fail this test at teardown


def test_a_test_that_reaches_for_the_server_fails():
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           f"{os.path.join('tests', 'test_update_guard.py')}::test_probe_leaks_on_purpose"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, cwd=ROOT,
                          env=dict(os.environ, MTF_GUARD_PROBE="1", PYTHONIOENCODING="utf-8"))
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0, out[-800:]
    assert "tried to reach the update server" in out
    assert "chaekgalpi.co.kr/api/tools/musictag/latest" in out


@pytest.mark.parametrize("url", ["https://musicbrainz.org/ws/2/", "https://chaekgalpi.co.kr.example.com/",
                                 "https://notchaekgalpi.co.kr/"])
def test_only_the_update_server_is_matched(url):
    assert not update_guard.is_update_server(url)
