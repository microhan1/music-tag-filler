"""Update check: once a day, off switch, silent failures, what is sent, when a notice shows.
The network is always faked - these tests never reach the real server."""
from __future__ import annotations

import io
import json
import os
import socket
import sys
import urllib.error
import urllib.parse

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import prefs as prefs_mod  # noqa: E402
import update_check as uc  # noqa: E402

DAY = "2026-10-13"
OK = {"slug": "musictag", "latest": "0.3.0", "tag": "v0.3.0", "client": "0.2.1", "updateAvailable": True,
      "url": "https://chaekgalpi.co.kr/tools/musictag?utm_source=app&utm_medium=update"}


class FakeRoot:
    """after() runs the callback at once; the background thread is run inline (see fixture)."""

    def __init__(self):
        self.delays = []

    def after(self, ms, fn):
        self.delays.append(ms)
        fn()


@pytest.fixture(autouse=True)
def inline_threads(monkeypatch):
    class InlineThread:
        def __init__(self, target, name=None, daemon=None):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(uc.threading, "Thread", InlineThread)


def run(prefs, fetcher, day=DAY):
    """One app start: schedule the check; the caller records the day only when answered (as the GUI does)."""
    results = []

    def on_result(info, answered):
        results.append(info)
        if answered:
            prefs.update_check_last = day

    root = FakeRoot()
    scheduled = uc.check_async(root, "musictag", "0.2.1", prefs, on_result, fetcher=fetcher, day=day)
    return scheduled, results, root


def counting(answer):
    calls = []

    def fetcher(slug, version):
        calls.append((slug, version))
        return answer

    return fetcher, calls


# ------------------------------------------------------------------ how often
def test_same_day_twice_asks_once():
    p = prefs_mod.Prefs()
    fetcher, calls = counting(OK)
    run(p, fetcher)
    run(p, fetcher)
    assert len(calls) == 1
    run(p, fetcher, day="2026-10-14")
    assert len(calls) == 2


def test_switched_off_never_asks():
    p = prefs_mod.Prefs(update_check=False)
    fetcher, calls = counting(OK)
    scheduled, results, root = run(p, fetcher)
    assert not scheduled and calls == [] and results == []


def test_offline_does_not_use_up_the_day():
    p = prefs_mod.Prefs()
    fetcher, calls = counting(None)  # no answer
    run(p, fetcher)
    run(p, fetcher)
    assert len(calls) == 2 and p.update_check_last == ""


def test_waits_one_and_a_half_seconds_first():
    _, _, root = run(prefs_mod.Prefs(), counting(OK)[0])
    assert root.delays[0] == 1500


# ------------------------------------------------------------------ what is sent
class FakeResp(io.BytesIO):
    def __init__(self, body: bytes, status: int = 200):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_request_carries_only_slug_version_and_os():
    seen = {}

    def opener(req, timeout):
        seen["url"], seen["timeout"] = req.full_url, timeout
        seen["headers"] = {k.lower(): v for k, v in req.header_items()}
        return FakeResp(json.dumps(OK).encode())

    assert uc.fetch("musictag", "0.2.1", opener=opener) == OK
    url = urllib.parse.urlsplit(seen["url"])
    assert (url.scheme, url.netloc, url.path) == ("https", "chaekgalpi.co.kr", "/api/tools/musictag/latest")
    assert urllib.parse.parse_qs(url.query) == {"v": ["0.2.1"], "os": ["win"]}
    assert seen["timeout"] == 4.0
    assert seen["headers"]["user-agent"] == "chaekgalpi-tool/musictag/0.2.1"
    assert set(seen["headers"]) <= {"user-agent", "accept"}  # nothing else about the user or machine


@pytest.mark.parametrize("behaviour", ["urlerror", "timeout", "http500", "badjson", "list", "status500", "oserror"])
def test_failures_are_silent(behaviour):
    def opener(req, timeout):
        if behaviour == "urlerror":
            raise urllib.error.URLError("offline")
        if behaviour == "timeout":
            raise socket.timeout("slow")
        if behaviour == "http500":
            raise urllib.error.HTTPError(req.full_url, 500, "boom", {}, None)
        if behaviour == "oserror":
            raise OSError("reset")
        if behaviour == "badjson":
            return FakeResp(b"<html>not json")
        if behaviour == "list":
            return FakeResp(b"[1, 2]")
        return FakeResp(json.dumps(OK).encode(), status=500)

    assert uc.fetch("musictag", "0.2.1", opener=opener) is None


# ------------------------------------------------------------------ when a notice shows
@pytest.mark.parametrize("flag", [False, None, "true", 1])
def test_no_notice_unless_server_says_true(flag):
    assert uc.interpret(dict(OK, updateAvailable=flag), "0.2.1") is None


def test_notice_once_when_newer():
    p = prefs_mod.Prefs()
    fetcher, _ = counting(OK)
    _, results, _ = run(p, fetcher)
    assert len(results) == 1 and results[0] == uc.UpdateInfo("0.3.0", "0.2.1", OK["url"])


def test_later_hides_that_version_but_not_a_newer_one():
    p = prefs_mod.Prefs(update_check_skipped="0.3.0")
    assert uc.interpret(OK, "0.2.1", p.update_check_skipped) is None
    newer = dict(OK, latest="0.3.1")
    assert uc.interpret(newer, "0.2.1", p.update_check_skipped).latest == "0.3.1"


@pytest.mark.parametrize("url", ["https://github.com/microhan1/music-tag-filler/releases", "http://chaekgalpi.co.kr/tools/x",
                                 "https://chaekgalpi.co.kr.evil.example/", "javascript:alert(1)", None, 5])
def test_only_pages_of_the_tools_site_are_opened(url):
    assert uc.interpret(dict(OK, url=url), "0.2.1") is None


@pytest.mark.parametrize("latest", ["", "   ", None, 3, "x" * 40])
def test_odd_versions_show_nothing(latest):
    assert uc.interpret(dict(OK, latest=latest), "0.2.1") is None


# ------------------------------------------------------------------ settings
def test_settings_are_type_checked(monkeypatch):
    import i18n

    monkeypatch.setattr(i18n, "load_settings", lambda: {"update_check": "no", "update_check_last": 20261013,
                                                        "update_check_skipped": ["0.3.0"]})
    p = prefs_mod.load()
    assert p.update_check is True and p.update_check_last == "" and p.update_check_skipped == ""
