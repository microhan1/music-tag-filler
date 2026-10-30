"""The window must fit the screen without the taskbar at every display scale (2026-10-30).

Up to v0.2.5 the window opened at 1140×820 times the scale wherever Windows put it: at 150%
that is 1710×1230, taller than a 1920×1080 or 1920×1200 screen, and the save row and status
line were below the taskbar (LESSONS A25). fit_window is checked on its own for 1920×1080,
1366×768, 1280×720 and two larger screens at 100, 125 and 150%; then the real App is shown
in a child process, one per scale, in a work area of each of those sizes placed off-screen.
No settings are written, nothing goes online (the child counts it), the user's screen is
not used.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SCREENS = [(1920, 1080), (1366, 768), (1280, 720), (1920, 1200), (2880, 1800)]
SCALES = [1.0, 1.25, 1.5]
# Too short at that scale for the header, the whole top pane and the save row (about 520 points of
# window; whether Windows even offers these scales on such screens is not checked): only the save
# row and status line are required there. The top pane is cut at its bottom, the cover button first.
SHORT = {((1280, 720), 1.25), ((1280, 720), 1.5), ((1366, 768), 1.5)}


def work_of(screen, scale, left=0, top=0):
    """The work area of a screen with a 48-point taskbar at the bottom."""
    w, h = screen
    return left, top, left + w, top + h - round(48 * scale)


def frame_of(scale):
    s = lambda n: round(n * scale)  # noqa: E731
    return s(8), s(31), s(8), s(8)


@pytest.mark.parametrize("scale", SCALES)
@pytest.mark.parametrize("screen", SCREENS)
def test_fit_window_keeps_the_whole_window_in_the_work_area(screen, scale):
    from gui import fit_window

    px = lambda n: round(n * scale)  # noqa: E731
    work, frame = work_of(screen, scale), frame_of(scale)
    want, least = (px(1140), px(820)), (px(960), px(700))
    w, h, x, y, min_w, min_h = fit_window(work, frame, want, least)
    fl, ft, fr, fb = frame
    assert work[0] <= x and x + fl + w + fr <= work[2]
    assert work[1] <= y and y + ft + h + fb <= work[3]
    room_w, room_h = work[2] - work[0] - fl - fr, work[3] - work[1] - ft - fb
    # as large as wanted where there is room, never smaller than needed
    assert w == min(want[0], room_w) and h == min(want[1], room_h)
    assert (min_w, min_h) == (min(least[0], room_w), min(least[1], room_h))
    assert min_w <= w and min_h <= h


def test_fit_window_follows_a_taskbar_on_the_left_or_top():
    from gui import fit_window

    frame = frame_of(1.5)
    for work in [(72, 0, 1920, 1080), (0, 72, 1920, 1080), (-1920, 0, 0, 1032)]:
        w, h, x, y, _mw, _mh = fit_window(work, frame, (1710, 1230), (1440, 1050))
        assert work[0] <= x and x + frame[0] + w + frame[2] <= work[2]
        assert work[1] <= y and y + frame[1] + h + frame[3] <= work[3]


def test_a_large_screen_keeps_the_size_it_always_had():
    from gui import fit_window

    w, h, *_rest, min_w, min_h = fit_window(work_of((2880, 1800), 1.5), frame_of(1.5), (1710, 1230), (1440, 1050))
    assert (w, h, min_w, min_h) == (1710, 1230, 1440, 1050)


CHILD = textwrap.dedent(r"""
    import json, os, sys, time
    sys.stdout.reconfigure(encoding="utf-8")
    sys.path.insert(0, {root!r}); os.chdir({root!r})
    sys.path.insert(0, os.path.join({root!r}, "tests"))
    SCALE, SCREENS = {scale!r}, {screens!r}
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

    class ScaledTk(tk.Tk):  # fonts and px() at the scale under test; the frame stays this PC's
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.tk.call("tk", "scaling", SCALE * 96 / 72)

    gui._HAS_DND = False
    gui.tk.Tk = ScaledTk
    app = gui.App()

    def pump(ms):
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            app.root.update()
            time.sleep(0.01)

    def outer():
        if sys.platform != "win32":
            return None
        import ctypes
        from ctypes import wintypes
        r = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(int(app.root.wm_frame(), 16), ctypes.byref(r))
        return [r.left, r.top, r.right, r.bottom]

    def box(w):
        return [w.winfo_rootx(), w.winfo_rooty(), w.winfo_rootx() + w.winfo_width(), w.winfo_rooty() + w.winfo_height()]

    app.root.geometry("+-6000+-6000")
    pump(300)
    app.files = [gui.FileState(path=f"C:\\music\\song-{{i}}.mp3") for i in range(2)]
    for _ in app.files:
        app.lst_files.insert("end", "")
    app._refresh_list()
    pump(200)
    for sw, sh in SCREENS:
        work = (-6000, -6000, -6000 + sw, -6000 + sh - round(48 * SCALE))
        app._place_window(work)
        app._fit_pending = True  # a new window: the top pane is fitted again, as at start
        pump(300)
        app._fit_top_pane()
        pump(100)
        b = app.btn_cover_all
        print(json.dumps({{
            "screen": [sw, sh], "work": work, "outer": outer(), "client": box(app.root),
            "cover_all": box(b), "cover_all_ok": b.winfo_ismapped() and b.winfo_height() >= b.winfo_reqheight(),
            "top": box(app.frm_top), "save": box(app.btn_save), "status": box(app.lbl_status),
            "tree": box(app.tree), "row": app.px(gui.THUMB_PX + 8),
        }}), flush=True)
    app._closing = True
    app._thumb_pool.shutdown(wait=False, cancel_futures=True)
    app.covers.close()
    app.root.destroy()
    print("LEAKS", len(guard.calls), flush=True)
""")


def inside(inner, outer) -> bool:
    return outer[0] <= inner[0] and inner[2] <= outer[2] and outer[1] <= inner[1] and inner[3] <= outer[3]


@pytest.mark.parametrize("scale", SCALES)
def test_real_window_fits_and_shows_the_cover_button_save_row_and_status(scale):
    pytest.importorskip("tkinter")
    code = CHILD.format(root=ROOT, scale=scale, screens=SCREENS)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8",
                         timeout=120, env=env)
    assert out.returncode == 0, out.stderr[-2000:]
    lines = out.stdout.splitlines()
    assert "LEAKS 0" in lines, out.stdout[-2000:]
    results = [json.loads(line) for line in lines if line.startswith("{")]
    assert len(results) == len(SCREENS)
    for r in results:
        where = f"{r['screen']} at {scale:.0%}"
        if r["outer"] is not None:  # border and title bar included
            assert inside(r["outer"], r["work"]), where
        assert inside(r["client"], r["work"]), where
        assert inside(r["save"], r["client"]), where
        assert inside(r["status"], r["client"]), where
        if (tuple(r["screen"]), scale) in SHORT:
            continue
        assert r["cover_all_ok"], where
        assert inside(r["cover_all"], r["top"]) and inside(r["top"], r["client"]), where
