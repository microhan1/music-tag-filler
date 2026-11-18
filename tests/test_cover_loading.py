"""「표지 불러오는 중…」 in the cover box (2026-11-18, 사장님 요청, LESSONS A29).

Up to v0.2.10 the box showed the note (the "no cover" picture) while a cover was still being
read or downloaded, so a file waiting for its cover looked like a file without one. Now the box
has three looks: the cover, the note, and 「Loading cover…」 on a plain square.

- a pick's download (the user's pick, also while it waits its turn, and the batch's own pick)
  shows the loading look from the moment it is asked for until it ends, whatever the outcome;
- reading a file's own cover or a stored one happens off the Tk thread, and the loading look
  appears only if that takes longer than COVER_LOAD_DELAY_MS (no flash for a quick read);
- a read or download that ends after the user moved to another file is not drawn over it.

The App is real, shown off-screen, writes no settings and never goes online: searching and the
cover download are replaced, and conftest refuses any outside connection anyway. Covers are
small PNGs made here; the slow file reads are made slow by holding them on an Event.
"""
from __future__ import annotations

import io
import os
import textwrap
import subprocess
import sys
import threading
import time

import pytest

import i18n
import prefs as prefs_mod
import update_check as uc
from match import Candidate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RED, GREEN, BLUE = (200, 30, 30), (30, 160, 60), (40, 60, 200)


def _png(color) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 40), color).save(buf, "PNG")
    return buf.getvalue()


def run_until(app, cond, timeout: float = 10.0) -> None:
    """Run the real event loop (workers and the cover pool hand over with root.after)."""
    end = time.monotonic() + timeout

    def check():
        if cond() or time.monotonic() >= end:
            app.root.quit()
            return
        app.root.after(5, check)

    app.root.after(5, check)
    app.root.mainloop()
    assert cond(), "timed out"


def run_for(app, ms: int) -> None:
    end = time.monotonic() + ms / 1000
    run_until(app, lambda: time.monotonic() >= end, ms / 1000 + 5)


def idle(app) -> None:
    """No worker, no download waiting its turn (the 200 ms loop of LESSONS A28), no read pending."""
    run_until(app, lambda: (not app._busy() and not app._covers_poll and not app._covers_wanted
                            and app._cover_pending is None), 15.0)
    run_for(app, 60)  # the last after(0) calls of the worker


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
    a._cover_pool.shutdown(wait=False, cancel_futures=True)
    a.covers.close()
    a.root.destroy()
    mp.undo()
    i18n.set_lang(before, persist=False)


class Reads:
    """Stands in for FileState.read_cover_for_display: a file named in `slow` waits for its
    Event; `fail` raises like an unreadable file."""

    def __init__(self):
        self.slow: dict[str, threading.Event] = {}
        self.fail: set[str] = set()
        self.calls: list[str] = []

    def __call__(self, s):
        self.calls.append(s.path)
        gate = self.slow.get(s.path)
        if gate is not None:
            gate.wait(10)
        if s.path in self.fail:
            raise OSError("unreadable")
        return s.load_cover()


@pytest.fixture
def app(module_app, monkeypatch):
    import gui

    a = module_app
    a.clear_files()
    a.reads = Reads()
    monkeypatch.setattr(gui.FileState, "read_cover_for_display", lambda s: a.reads(s))
    a.painted: list = []  # every cover drawn: the colour of its corner, or None for the note
    real_paint = a._paint_cover
    monkeypatch.setattr(a, "_paint_cover",
                        lambda im: a.painted.append(None if im is None else im.getpixel((0, 0))) or real_paint(im))
    a.fetch_gate = threading.Event()
    a.fetch_gate.set()
    a.fetch_answer = {"Album R": _png(RED), "Album G": _png(GREEN)}
    a.fetch_raise = False
    a.fetched: list[str] = []

    def fetch_cover(cand, *x, cancel=None, **k):
        a.fetched.append(cand.album)
        while not a.fetch_gate.wait(0.02):
            if cancel is not None and cancel.is_set():
                return None
        if a.fetch_raise:
            raise RuntimeError("cover server answered garbage")
        return a.fetch_answer.get(cand.album)

    monkeypatch.setattr(gui.pipeline, "fetch_cover", fetch_cover)
    a.errors: list = []
    for name in ("showerror", "showwarning"):
        monkeypatch.setattr(gui.messagebox, name, lambda *x, **k: a.errors.append(x))
    yield a
    for gate in a.reads.slow.values():
        gate.set()
    a.fetch_gate.set()
    idle(a)
    a.clear_files()


def add_file(app, name: str, cover=None, *, with_info: bool = True):
    """A file in the list: `cover` is a colour (its cover, held in the CoverStore as if read
    from the file) or None (no cover). Nothing is read from disk: reads go through app.reads."""
    import gui
    import tags

    s = gui.FileState(path=os.path.join("C:\\music", name))
    if with_info:
        s.info = tags.FileInfo(path=s.path, fmt="MP3", length=200.0, bitrate=320, sample_rate=44100,
                               tags=tags.Tags(title=name), cover=None, cover_mime="")
        s.values = s.info.tags.as_dict()
    if cover is not None:
        s.cover_key, s.cover_changed = app.covers.put(_png(cover)), True
    s.candidates = [Candidate(title="Song", artist="Artist", album=album, score=95, sources=["iTunes"],
                              cover_url=f"https://covers.invalid/{album}")
                    for album in ("Album R", "Album G", "Album X")]
    app.files.append(s)
    app._refresh_list()
    return s


def pick(app, s, album: str) -> None:
    """What a double-click on the row does."""
    app._show_file(s)
    row = next(i for i, c in enumerate(s.candidates) if c.album == album)
    app.tree.selection_set(str(row))
    app.apply_selected()


def shows(app) -> str:
    return app._cover_state


def loading_text_shown(app) -> bool:
    return (app.lbl_cover.cget("text") == i18n.t("cover_loading")
            and app.lbl_cover.cget("image") == str(app._cover_blank))


# ---------------------------------------------------------------- the file's own cover


def test_a_quick_read_shows_the_cover_without_flashing_the_loading_text(app, monkeypatch):
    s = add_file(app, "a.mp3", RED)
    flashes = []
    real = app._paint_cover_loading
    monkeypatch.setattr(app, "_paint_cover_loading", lambda: flashes.append(1) or real())
    app._show_file(s)
    idle(app)
    run_for(app, 250)  # past COVER_LOAD_DELAY_MS
    assert shows(app) == "cover" and app.painted[-1] == RED
    assert app.lbl_cover.cget("text") == ""
    assert flashes == []


def test_a_slow_read_shows_loading_then_the_cover(app):
    import gui

    s = add_file(app, "slow.mp3", GREEN)
    app.reads.slow[s.path] = gate = threading.Event()
    app._show_file(s)
    run_for(app, gui.COVER_LOAD_DELAY_MS // 3)
    assert shows(app) != "loading"  # not yet: most reads are over by now
    run_until(app, lambda: shows(app) == "loading")
    assert loading_text_shown(app)
    gate.set()
    run_until(app, lambda: shows(app) == "cover")
    assert app.painted[-1] == GREEN and app.lbl_cover.cget("text") == ""


def test_a_slow_read_that_finds_nothing_ends_on_the_note(app):
    """The file said it had a cover but none could be decoded: the note, not a stuck text."""
    s = add_file(app, "broken.mp3", None)
    s.has_cover = True
    app.reads.slow[s.path] = gate = threading.Event()
    app._show_file(s)
    run_until(app, lambda: shows(app) == "loading")
    app.reads.fail.add(s.path)
    gate.set()
    run_until(app, lambda: shows(app) == "none")
    assert app.lbl_cover.cget("text") == "" and app.lbl_cover.cget("image") == str(app._placeholder)
    assert app.errors == []


def test_a_file_without_a_cover_shows_the_note_at_once_without_reading(app):
    s = add_file(app, "none.mp3", None)
    app._show_file(s)
    assert shows(app) == "none" and app._cover_pending is None
    assert app.reads.calls == []


def test_a_file_the_batch_has_not_opened_yet_is_read_for_its_cover(app):
    s = add_file(app, "queued.mp3", BLUE, with_info=False)
    app._show_file(s)
    idle(app)
    assert app.reads.calls == [s.path] and shows(app) == "cover" and app.painted[-1] == BLUE


def test_a_late_read_of_the_previous_file_is_not_drawn_over_the_next(app):
    """Click a slow file, then quickly another: the first read ends last and must be dropped."""
    first = add_file(app, "first.mp3", RED)
    second = add_file(app, "second.mp3", GREEN)
    app.reads.slow[first.path] = gate = threading.Event()
    app._show_file(first)
    run_for(app, 20)
    app._show_file(second)
    run_until(app, lambda: shows(app) == "cover")
    assert app.painted[-1] == GREEN
    gate.set()
    run_for(app, 300)
    assert RED not in app.painted and app.painted[-1] == GREEN and app.current is second


def test_switching_from_a_slow_file_to_one_without_a_cover_drops_the_loading_text(app):
    slow = add_file(app, "slow.mp3", RED)
    bare = add_file(app, "bare.mp3", None)
    app.reads.slow[slow.path] = gate = threading.Event()
    app._show_file(slow)
    run_until(app, lambda: shows(app) == "loading")
    app._show_file(bare)
    assert shows(app) == "none" and app.lbl_cover.cget("text") == ""
    gate.set()
    run_for(app, 300)
    assert shows(app) == "none" and RED not in app.painted


# ---------------------------------------------------------------- a pick's download


def test_a_pick_shows_loading_until_its_cover_arrives(app):
    s = add_file(app, "song.mp3", BLUE)  # it has a cover of its own: the pick replaces it
    app.fetch_gate.clear()
    pick(app, s, "Album G")
    assert shows(app) == "loading" and loading_text_shown(app)
    run_until(app, lambda: app.fetched == ["Album G"])
    run_for(app, 300)
    assert shows(app) == "loading"  # still downloading: not the old cover, not the note
    app.fetch_gate.set()
    idle(app)
    assert shows(app) == "cover" and app.painted[-1] == GREEN and s.cover_wait is None


def test_a_pick_whose_cover_is_not_found_goes_back_to_what_was_there(app):
    s = add_file(app, "song.mp3", BLUE)
    pick(app, s, "Album X")  # the server has nothing for it
    idle(app)
    assert shows(app) == "cover" and app.painted[-1] == BLUE and s.cover_wait is None
    assert app._status_key == "msg_cover_failed"
    bare = add_file(app, "bare.mp3", None)
    pick(app, bare, "Album X")
    idle(app)
    app._show_file(bare)
    assert shows(app) == "none" and bare.cover_wait is None


def test_a_download_that_breaks_does_not_leave_the_loading_text(app):
    s = add_file(app, "song.mp3", None)
    app.fetch_raise = True
    pick(app, s, "Album R")
    assert shows(app) == "loading"
    idle(app)
    assert shows(app) == "none" and s.cover_wait is None and app.lbl_cover.cget("text") == ""
    assert len(app.errors) == 1  # the worker's error box, as for any other failure
    app.errors.clear()


def test_a_pick_on_another_file_is_not_drawn_over_the_file_on_screen(app):
    one = add_file(app, "one.mp3", None)
    two = add_file(app, "two.mp3", BLUE)
    app.fetch_gate.clear()
    pick(app, one, "Album R")
    assert shows(app) == "loading"
    app._show_file(two)
    run_until(app, lambda: shows(app) == "cover")
    assert app.painted[-1] == BLUE
    app.fetch_gate.set()
    idle(app)
    assert app.current is two and app.painted[-1] == BLUE and RED not in app.painted
    app._show_file(one)  # back to the first file: its new cover is there
    idle(app)
    assert shows(app) == "cover" and app.painted[-1] == RED


def test_coming_back_to_a_file_still_downloading_shows_loading_again(app):
    one = add_file(app, "one.mp3", None)
    two = add_file(app, "two.mp3", None)
    app.fetch_gate.clear()
    pick(app, one, "Album G")
    app._show_file(two)
    assert shows(app) == "none"
    app._show_file(one)
    assert shows(app) == "loading"
    app.fetch_gate.set()
    idle(app)
    assert shows(app) == "cover" and app.painted[-1] == GREEN


def test_a_pick_waiting_its_turn_behind_another_job_shows_loading(app):
    """LESSONS A28: while another job holds the worker the download waits; it is still on its way."""
    s = add_file(app, "song.mp3", None)
    hold = threading.Event()
    app._run(hold.wait, 10)
    pick(app, s, "Album R")
    run_for(app, 450)
    assert app.fetched == [] and shows(app) == "loading"
    hold.set()
    idle(app)
    assert app.fetched == ["Album R"] and shows(app) == "cover" and app.painted[-1] == RED


def test_cancel_while_waiting_its_turn_drops_the_loading_text(app):
    s = add_file(app, "song.mp3", BLUE)
    hold = threading.Event()
    app._run(hold.wait, 10)
    pick(app, s, "Album R")
    assert shows(app) == "loading"
    app.cancel()
    hold.set()
    idle(app)
    assert app.fetched == [] and s.cover_wait is None
    assert shows(app) == "cover" and app.painted[-1] == BLUE  # its own cover again


def test_an_image_file_picked_while_a_download_runs_wins(app, tmp_path):
    s = add_file(app, "song.mp3", None)
    image = tmp_path / "front.png"
    image.write_bytes(_png(BLUE))
    app.fetch_gate.clear()
    pick(app, s, "Album R")
    run_until(app, lambda: app.fetched == ["Album R"])
    app._set_cover_from_file(str(image))
    run_until(app, lambda: shows(app) == "cover")
    assert app.painted[-1] == BLUE
    app.fetch_gate.set()
    idle(app)
    assert shows(app) == "cover" and app.painted[-1] == BLUE and s.load_cover() == _png(BLUE)


def test_the_batch_pick_shows_loading_while_its_cover_downloads(app):
    s = add_file(app, "song.mp3", None)
    app._show_file(s)
    s.selected = s.candidates[1]
    app.fetch_gate.clear()
    app._run(app._fetch_pick_cover, s, s.candidates[1])
    run_until(app, lambda: shows(app) == "loading")
    app.fetch_gate.set()
    idle(app)
    assert shows(app) == "cover" and app.painted[-1] == GREEN and s.cover_wait is None


def test_the_batch_pick_with_no_cover_found_ends_on_the_note(app):
    s = add_file(app, "song.mp3", None)
    app._show_file(s)
    s.selected = s.candidates[2]  # Album X: nothing on the server
    app._run(app._fetch_pick_cover, s, s.candidates[2])
    idle(app)
    assert shows(app) == "none" and s.cover_wait is None and app.errors == []


def test_the_loading_text_follows_the_language(app):
    s = add_file(app, "song.mp3", None)
    app.fetch_gate.clear()
    pick(app, s, "Album R")
    try:
        for lang in ("en", "zh-CN", "ja", "ko"):
            i18n.set_lang(lang, persist=False)
            app._apply_texts()
            assert app.lbl_cover.cget("text") == i18n.t("cover_loading") != ""
    finally:
        i18n.set_lang("ko", persist=False)
        app._apply_texts()


# ---------------------------------------------------------------- fits the box at every scale

FIT_CHILD = textwrap.dedent(r"""
    import json, os, sys, time
    sys.stdout.reconfigure(encoding="utf-8")
    sys.path.insert(0, {root!r}); os.chdir({root!r})
    sys.path.insert(0, os.path.join({root!r}, "tests"))
    SCALE = {scale!r}
    import tkinter as tk
    import i18n; i18n.save_settings = lambda data: None; i18n.set_lang("ko", persist=False)
    import prefs as prefs_mod
    prefs_mod.save = lambda *a, **k: None
    prefs_mod.load = lambda: prefs_mod.Prefs()
    import update_check, update_guard
    guard = update_guard.make_opener()
    update_guard.install(update_check, guard)  # this child is outside conftest's reach
    update_check.check_async = lambda *a, **k: True
    import gui
    gui.App._probe_online = lambda self: None

    class ScaledTk(tk.Tk):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.tk.call("tk", "scaling", SCALE * 96 / 72)

    gui._HAS_DND = False
    gui.tk.Tk = ScaledTk
    app = gui.App()
    app.root.geometry("+-6000+-6000")
    app.root.update()
    lbl = app.lbl_cover
    app._paint_cover(None)
    app.root.update()
    empty = [lbl.winfo_reqwidth(), lbl.winfo_reqheight()]
    for lang in ("ko", "en", "zh-CN", "ja"):
        i18n.set_lang(lang, persist=False)
        app._paint_cover_loading()
        app._apply_texts()
        app.root.update()
        text = lbl.cget("text")
        print(json.dumps({{"lang": lang, "empty": empty, "loading": [lbl.winfo_reqwidth(), lbl.winfo_reqheight()],
                          "text_w": app.font_body.measure(text), "wrap": int(str(lbl.cget("wraplength"))),
                          "box": app.px(gui.COVER_PX)}}), flush=True)
    app._closing = True
    app._thumb_pool.shutdown(wait=False, cancel_futures=True)
    app._cover_pool.shutdown(wait=False, cancel_futures=True)
    app.covers.close()
    app.root.destroy()
    print("LEAKS", len(guard.calls), flush=True)
""")


@pytest.mark.parametrize("scale", [1.0, 1.25, 1.5])
def test_the_loading_text_fits_the_cover_box_in_every_language(scale):
    """A longer text would widen the label and push the cover column (the box is a fixed square)."""
    import json

    code = FIT_CHILD.format(root=ROOT, scale=scale)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8",
                         timeout=120, env=env)
    assert out.returncode == 0, out.stderr[-2000:]
    lines = out.stdout.splitlines()
    assert "LEAKS 0" in lines, out.stdout[-2000:]
    results = [json.loads(line) for line in lines if line.startswith("{")]
    assert [r["lang"] for r in results] == ["ko", "en", "zh-CN", "ja"]
    for r in results:
        assert r["loading"] == r["empty"], r  # the text sits inside the square, the label does not grow
        assert r["text_w"] <= r["wrap"] < r["box"], r  # one line, not even wrapped
