"""A pick made while the list is still being searched gets its cover too (LESSONS A28, 2026-11-17).

While a batch search runs, the buttons are greyed out but a double-click or Enter in the
result table still applies a row. The tags changed and the cover did not: the cover download
went through _run, which drops a job while another one holds the worker. Now the cover
waits its turn: the batch fetches it before the next file, any other job hands it on when
it ends.

Every file here is a copy of a committed sample in tmp_path: no user music. The App is real,
shown off-screen, writes no settings and never goes online: searching and the cover download
are replaced (conftest refuses any outside connection anyway).
"""
from __future__ import annotations

import io
import os
import shutil
import threading
import time

import pytest

import i18n
import pipeline
import prefs as prefs_mod
import update_check as uc
from match import Candidate
from tests.test_tags import FIXTURES, _ensure_fixtures

GATED = 4  # the batch stops before searching the 4th file until the test lets it go (app.gate)
LAST = 5  # ... and in the 5th file's search while app.gate_last is clear
COLORS = {"Album A": (200, 30, 30), "Album B": (30, 160, 60)}


def _png(color) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 40), color).save(buf, "PNG")
    return buf.getvalue()


def run_until(app, cond, timeout: float = 15.0) -> None:
    """Run the real event loop (workers hand over with root.after) until cond() is true."""
    end = time.monotonic() + timeout

    def check():
        if cond() or time.monotonic() >= end:
            app.root.quit()
            return
        app.root.after(10, check)

    app.root.after(10, check)
    app.root.mainloop()
    assert cond(), "timed out"


def wait_idle(app) -> None:
    settled = {"at": None}

    def done():
        if app._busy() or getattr(app, "_covers_poll", False):
            settled["at"] = None
            return False
        settled["at"] = settled["at"] or time.monotonic()
        return time.monotonic() - settled["at"] > 0.15  # let the worker's last after(0) calls run

    run_until(app, done, 30.0)


@pytest.fixture(scope="module")
def module_app():
    import gui

    before = i18n.current_lang()
    mp = pytest.MonkeyPatch()
    mp.setattr(i18n, "save_settings", lambda data: None)
    mp.setattr(prefs_mod, "save", lambda *a, **k: None)
    mp.setattr(prefs_mod, "load", lambda: prefs_mod.Prefs())
    mp.setattr(gui.App, "_probe_online", lambda self: None)
    real_check = uc.check_async
    mp.setattr(uc, "check_async", lambda *a, **k: True)
    i18n.set_lang("ko", persist=False)
    a = gui.App()
    mp.setattr(uc, "check_async", real_check)
    a.root.geometry("+-5000+-5000")
    a.root.update()
    yield a
    a._closing = True
    a._thumb_pool.shutdown(wait=False, cancel_futures=True)
    a.covers.close()
    a.root.destroy()
    mp.undo()
    i18n.set_lang(before, persist=False)


@pytest.fixture
def app(module_app, monkeypatch, tmp_path):
    """Five mp3 copies; every search answers two rows below the auto-pick bar (nothing is
    picked by the batch); the search of the 4th file waits for app.gate."""
    import gui

    a = module_app
    a.clear_files()
    a.var_only_missing_cover.set(False)
    _ensure_fixtures()
    a.paths = []
    for n in range(1, 6):
        path = os.path.join(tmp_path, f"{n:02d}-song.mp3")
        shutil.copy(os.path.join(FIXTURES, "sample-a.mp3"), path)
        a.paths.append(path)
    a.gate = threading.Event()
    a.gate_last = threading.Event()
    a.gate_last.set()
    a.searches: list[str] = []

    def search_text(query, *x, cancel=None, **k):
        a.searches.append(query)
        gate = {GATED: a.gate, LAST: a.gate_last}.get(len(a.searches))
        if gate is not None:
            while not gate.wait(0.05):
                if cancel is not None and cancel.is_set():
                    break
        rows = [Candidate(title="Song", artist="Artist", album=album, score=50, sources=["iTunes"],
                          cover_url=f"https://covers.invalid/{album}") for album in COLORS]
        return pipeline.SearchResult(rows, [])

    a.fetched: list[str] = []

    def fetch_cover(cand, *x, **k):
        a.fetched.append(cand.album)
        return _png(COLORS[cand.album])

    monkeypatch.setattr(gui.pipeline, "search_text", search_text)
    monkeypatch.setattr(gui.pipeline, "fetch_cover", fetch_cover)
    errors: list = []
    for name in ("showerror", "showwarning"):
        monkeypatch.setattr(gui.messagebox, name, lambda *x, **k: errors.append(x))
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *x, **k: None)
    yield a
    a.gate.set()
    a.gate_last.set()
    wait_idle(a)
    assert errors == []
    a.clear_files()


def start_batch_and_hold(app):
    """Add the files and run until the batch is waiting on the 4th search (files 1-3 are done)."""
    app.add_paths(list(app.paths))
    run_until(app, lambda: len(app.searches) == GATED and app.files[2].candidates)
    assert app._busy()


def pick(app, s, album: str) -> None:
    """What a double-click on the row does: show the file, select the row, apply it."""
    app._show_file(s)
    row = next(i for i, c in enumerate(s.candidates) if c.album == album)
    app.tree.selection_set(str(row))
    app.apply_selected()


def cover_of(s) -> bytes | None:
    return s.load_cover() if s.cover_changed else None


def test_a_pick_during_the_batch_gets_its_cover_before_the_next_file(app):
    start_batch_and_hold(app)
    first = app.files[0]
    pick(app, first, "Album B")
    assert first.values["album"] == "Album B"  # the tags changed at once, as before
    assert app.fetched == []  # the worker is still searching file 4
    app.gate.set()
    # the cover is fetched at the top of the next file, before its search
    run_until(app, lambda: len(app.searches) > GATED or not app._busy())
    run_until(app, lambda: cover_of(first) is not None)
    assert app.fetched == ["Album B"]
    assert cover_of(first) == _png(COLORS["Album B"])
    wait_idle(app)
    assert app.fetched == ["Album B"] and cover_of(first) == _png(COLORS["Album B"])


def test_the_last_pick_wins_when_the_user_changes_their_mind(app):
    start_batch_and_hold(app)
    first = app.files[0]
    pick(app, first, "Album A")
    pick(app, first, "Album B")
    app.gate.set()
    wait_idle(app)
    assert app.fetched == ["Album B"]  # the first pick's cover is not even asked for
    assert first.selected.album == "Album B" and cover_of(first) == _png(COLORS["Album B"])


def test_picks_on_several_files_each_get_their_own_cover(app):
    start_batch_and_hold(app)
    one, two = app.files[0], app.files[1]
    pick(app, one, "Album A")
    pick(app, two, "Album B")
    app.gate.set()
    wait_idle(app)
    assert sorted(app.fetched) == ["Album A", "Album B"]
    assert cover_of(one) == _png(COLORS["Album A"]) and cover_of(two) == _png(COLORS["Album B"])


def test_the_cover_shows_when_the_picked_file_is_on_screen(app, monkeypatch):
    start_batch_and_hold(app)
    shown: list = []
    real_show = app._show_cover
    monkeypatch.setattr(app, "_show_cover", lambda data: shown.append(data) or real_show(data))
    pick(app, app.files[0], "Album B")
    app.gate.set()
    wait_idle(app)
    assert _png(COLORS["Album B"]) in shown


def test_a_pick_after_the_last_file_waits_for_the_batch_to_end(app):
    """Picked while the batch is past its last top-of-loop check: the waiting loop catches it."""
    app.gate_last.clear()
    start_batch_and_hold(app)
    app.gate.set()
    run_until(app, lambda: len(app.searches) == LAST)  # file 5 is being searched: no more checks in the loop
    pick(app, app.files[0], "Album A")
    assert app._busy() and app.fetched == []
    app.gate_last.set()
    wait_idle(app)
    assert app.fetched == ["Album A"] and cover_of(app.files[0]) == _png(COLORS["Album A"])


def test_cancel_drops_the_waiting_covers(app):
    start_batch_and_hold(app)
    pick(app, app.files[0], "Album B")
    app.cancel()
    wait_idle(app)
    assert app.fetched == []
    assert app.files[0].values["album"] == "Album B"  # the tags of the pick stay; the user can pick again


def test_a_pick_when_nothing_runs_fetches_at_once(app):
    start_batch_and_hold(app)
    app.gate.set()
    wait_idle(app)
    pick(app, app.files[2], "Album A")
    assert app._busy()  # straight to the worker, as before
    wait_idle(app)
    assert app.fetched == ["Album A"] and cover_of(app.files[2]) == _png(COLORS["Album A"])


def test_enter_in_the_query_box_during_the_batch_keeps_the_rows(app):
    """The search button is greyed out but Enter still reached search_text, which emptied
    the table and then had its job dropped."""
    start_batch_and_hold(app)
    first = app.files[0]
    app._show_file(first)
    rows = list(first.candidates)
    app.var_query.set("something else")
    app.ent_query.focus_force()
    app.ent_query.event_generate("<Return>", when="now")
    app.root.update()
    assert app.var_query.get() == "something else"
    assert first.candidates == rows and len(app.tree.get_children()) == len(rows)
    assert app.searches.count("something else") == 0
