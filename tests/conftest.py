"""Every test runs with the update server out of reach (see tests/update_guard.py).

- check_async's default fetcher answers "offline" (tests that want an answer pass fetcher=);
- fetch's default opener and urllib.request.urlopen refuse chaekgalpi.co.kr and record it;
- a test that tried to reach the server fails at teardown, naming the URL.

Counted before this was added (2026-10-15): 0 requests in the whole suite of 274 tests,
including the child processes of test_update_close.py.

Below that, every test also runs without any outside network (2026-10-26): a socket
connection or a name lookup to anything but this machine is refused and recorded, and the
test fails at teardown. MusicBrainz, iTunes, AcoustID and LRCLIB lookups can therefore never
leave a test, whatever their default arguments are bound to.
"""
import os
import socket
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


LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "")


def _is_local(host) -> bool:
    host = str(host or "").strip("[]").lower()
    return host in LOCAL_HOSTS or host.startswith("127.")


@pytest.fixture(autouse=True)
def network_blocked(monkeypatch):
    """Yields the list of refused (host, port) so a test can look at (and clear) it."""
    calls: list = []
    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def refuse(address):
        calls.append(address)
        raise OSError(f"outside network blocked in tests: {address!r}")

    def connect(self, address, *args):
        host = address[0] if isinstance(address, tuple) else address
        if not _is_local(host):
            refuse(address)
        return real_connect(self, address, *args)

    def connect_ex(self, address, *args):
        host = address[0] if isinstance(address, tuple) else address
        if not _is_local(host):
            refuse(address)
        return real_connect_ex(self, address, *args)

    def getaddrinfo(host, port, *args, **kwargs):
        if not _is_local(host):
            refuse((host, port))
        return real_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    yield calls
    if calls:
        pytest.fail(f"a test tried to reach the network: {calls}", pytrace=False)
