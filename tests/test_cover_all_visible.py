"""「이 표지를 목록 전체에」 must be whole on screen once a second file comes in (2026-10-30).

v0.2.5 set the split once, 50 ms after start, to a fixed height; the window was often not
laid out yet, the sash stayed at the top pane's height without the button, and the button
appeared under it as a thin line (LESSONS A24). The App here is real and shown off-screen
(a hidden window is not laid out); no settings are written and nothing goes online.
"""
from __future__ import annotations

import time

import pytest

import i18n
import prefs as prefs_mod
import update_check as uc


def pump(app, ms: int) -> None:
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        app.root.update()
        time.sleep(0.01)


@pytest.fixture(scope="module")
def app():
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
    pump(a, 300)
    yield a
    a._closing = True
    a._thumb_pool.shutdown(wait=False, cancel_futures=True)
    a.covers.close()
    a.root.destroy()
    mp.undo()
    i18n.set_lang(before, persist=False)


def set_files(app, n: int) -> None:
    import gui

    app.files = [gui.FileState(path=f"C:\\music\\song-{i}.mp3") for i in range(n)]
    app.lst_files.delete(0, "end")
    for _ in app.files:
        app.lst_files.insert("end", "")
    app._refresh_list()
    pump(app, 200)


def overflow(app) -> int:
    """How far the button's bottom edge reaches past the top pane's (negative: inside)."""
    b, top = app.btn_cover_all, app.frm_top
    return (b.winfo_rooty() + b.winfo_height()) - (top.winfo_rooty() + top.winfo_height())


def test_top_pane_is_laid_out_tall_enough_at_start(app):
    assert app.paned.sashpos(0) >= app.frm_top.winfo_reqheight()


@pytest.mark.parametrize("code", ["ko", "en", "zh-CN", "ja"])
def test_cover_all_button_is_whole_when_a_second_file_comes_in(app, code):
    app.var_lang.set(i18n.LANG_NAMES[code])
    app._on_lang()
    set_files(app, 1)
    assert not app.btn_cover_all.winfo_ismapped()
    # one file shown, the pane just fitting it: how v0.2.5 started at 100% and 125%
    app.paned.sashpos(0, app.frm_top.winfo_reqheight())
    pump(app, 100)
    set_files(app, 2)
    b = app.btn_cover_all
    assert b.winfo_ismapped()
    assert b.winfo_height() >= b.winfo_reqheight()  # not squeezed to a line
    assert overflow(app) <= 0
    set_files(app, 0)


def test_a_sash_the_user_moved_stays_through_a_resize(app):
    set_files(app, 2)
    pos = app.paned.sashpos(0)
    app.paned.sashpos(0, pos - app.px(60))  # the user drags it up to see more candidates
    moved = app.paned.sashpos(0)
    w, h = app.root.winfo_width(), app.root.winfo_height()
    app.root.geometry(f"{w}x{h + app.px(40)}+-5000+-5000")
    pump(app, 200)
    assert app.paned.sashpos(0) == moved
    app.root.geometry(f"{w}x{h}+-5000+-5000")
    set_files(app, 0)
