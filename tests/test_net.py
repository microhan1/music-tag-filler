"""Rate limiter behaviour (no network)."""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import net  # noqa: E402
import search_itunes  # noqa: E402


def test_window_allows_burst_then_paces():
    th = net._Throttle()
    th.set_window("h", 3, 0.6)
    t0 = time.perf_counter()
    for _ in range(3):
        th.wait("h")
    burst = time.perf_counter() - t0
    th.wait("h")  # fourth call must wait for the first slot to expire
    paced = time.perf_counter() - t0
    assert burst < 0.2
    assert paced >= 0.5


def test_interval_hosts_still_space_requests():
    th = net._Throttle()
    th.set_interval("h", 0.3)
    t0 = time.perf_counter()
    th.wait("h")
    th.wait("h")
    assert time.perf_counter() - t0 >= 0.25


def test_slow_down_holds_the_host():
    th = net._Throttle()
    th.set_window("h", 5, 60.0)
    th.slow_down("h", 0.4)
    t0 = time.perf_counter()
    th.wait("h")
    assert time.perf_counter() - t0 >= 0.35


def test_empty_storefront_is_skipped(monkeypatch):
    calls = []

    def fake_get_json(url, params=None, **kwargs):
        calls.append(params["country"])
        return {"results": [{"wrapperType": "track", "trackName": "x", "artistName": "y"}]}

    monkeypatch.setattr(net, "get_json", fake_get_json)
    search_itunes.search("x", "KR")
    assert calls == ["US"]  # KR is never asked
    calls.clear()
    search_itunes.search("x", "JP")
    assert calls == ["JP"]  # a storefront with results is used as is
