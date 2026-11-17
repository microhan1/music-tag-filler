"""Check boxes show a tick (✓), not the clam theme's X (2026-11-17).

The window keeps the clam theme and swaps only the TCheckbutton.indicator element for an image
element drawn by check_indicator.py at the window's scale. These tests use the real App (shown
off-screen, no settings written, never online) and the images it made.
"""
from __future__ import annotations

import time

import pytest

import check_indicator as ci
import i18n
import prefs as prefs_mod
import update_check as uc

ACCENT = "#2563eb"


def _rgb(color: str) -> tuple[int, int, int]:
    return ci._rgb(color)


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


def _names(layout) -> list[str]:
    out = []
    for name, opts in layout:
        out.append(name)
        out += _names(opts.get("children", []))
    return out


def test_the_theme_stays_clam_and_only_the_indicator_is_swapped(app):
    from tkinter import ttk

    style = ttk.Style(app.root)
    assert style.theme_use() == "clam"
    names = _names(style.layout("TCheckbutton"))
    assert ci.ELEMENT in names and ci.OLD_ELEMENT not in names
    assert "Checkbutton.focus" in names and "Checkbutton.label" in names  # keyboard focus ring kept
    assert ci.ELEMENT in style.element_names()


def test_every_check_box_in_the_window_uses_the_tick(app):
    from tkinter import ttk

    boxes = [w for w in (app.chk_update, app.chk_only_missing_cover, app.chk_only_missing_cover_list,
                         app.chk_rename, app.chk_alert, app.chk_lyrics)]
    style = ttk.Style(app.root)
    for w in boxes:
        assert isinstance(w, ttk.Checkbutton)
        assert (w.cget("style") or "TCheckbutton") == "TCheckbutton"
        assert ci.ELEMENT in _names(style.layout(w.winfo_class()))

    def walk(w):
        yield w
        for c in w.winfo_children():
            yield from walk(c)

    found = [w for w in walk(app.root) if w.winfo_class() == "TCheckbutton"]
    assert len(found) == len(boxes)  # no other check box was missed


def test_same_size_and_text_position_as_the_clam_box(app):
    """A check box with clam's old indicator (size 14, margin 6) asks for the same space."""
    from tkinter import ttk

    style = ttk.Style(app.root)
    style.layout("OldX.TCheckbutton", ci._swap(style.layout("TCheckbutton"), ci.ELEMENT, ci.OLD_ELEMENT))
    style.configure("OldX.TCheckbutton", indicatorsize=app.px(14), indicatormargin=(0, 0, app.px(6), 0))
    for key in ("opt_rename", "opt_only_missing_cover", "opt_update_check"):
        new = ttk.Checkbutton(app.root, text=i18n.t(key))
        old = ttk.Checkbutton(app.root, text=i18n.t(key), style="OldX.TCheckbutton")
        try:
            assert (new.winfo_reqwidth(), new.winfo_reqheight()) == (old.winfo_reqwidth(), old.winfo_reqheight())
        finally:
            new.destroy()
            old.destroy()


def test_images_are_kept_and_sized_for_the_window_scale(app):
    imgs = app._check_images
    assert set(imgs) == {name for _, name in ci.STATE_MAP} | {"off"}
    size = ci.box_size(app.scale)
    gap = app.px(14) + app.px(6) - size
    for img in imgs.values():
        assert (img.width(), img.height()) == (size + gap, size)
        for y in range(size):  # the gap before the text is see-through
            for x in range(size, size + gap):
                assert img.transparency_get(x, y)
        assert img.transparency_get(0, 0)  # rounded corner


@pytest.mark.parametrize("scale, size", [(1.0, 15), (1.25, 19), (1.5, 22), (2.0, 30)])
def test_box_size_per_scale(scale, size):
    assert ci.box_size(scale) == size


def _pixels(rows):
    return [_rgb(c) for row in rows for c in row if c is not None]


def _near(a, b, tol=8):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


@pytest.mark.parametrize("scale", [1.0, 1.25, 1.5])
def test_ticked_box_is_accent_with_a_white_tick(scale):
    size = ci.box_size(scale)
    spec = ci.colours(ACCENT, "#1d4ed8")
    rows = ci.render(size, *spec["on"], bg="#f3f4f6")
    px = _pixels(rows)
    accent = sum(_near(p, _rgb(ACCENT)) for p in px)
    white = sum(_near(p, (255, 255, 255)) for p in px)
    assert accent > len(px) * 0.4 and white >= size  # a filled box and a real stroke
    # the tick is a ✓, not an X: the top-left and bottom-right corners inside the box stay accent
    q = size // 4
    assert _near(_rgb(rows[q][q]), _rgb(ACCENT)) and _near(_rgb(rows[size - 1 - q][size - 1 - q]), _rgb(ACCENT))
    # and the stroke passes through the lower middle (the bottom of the ✓)
    mid = [_rgb(rows[j][int(size * 0.43)]) for j in range(int(size * 0.55), int(size * 0.85))]
    assert any(_near(p, (255, 255, 255), 40) for p in mid)


@pytest.mark.parametrize("scale", [1.0, 1.25, 1.5])
def test_unticked_box_is_white_with_a_grey_border_and_no_mark(scale):
    size = ci.box_size(scale)
    rows = ci.render(size, *ci.colours(ACCENT, "#1d4ed8")["off"], bg="#f3f4f6")
    c = size // 2
    assert _rgb(rows[c][c]) == (255, 255, 255)
    inner = [_rgb(rows[j][i]) for j in range(3, size - 3) for i in range(3, size - 3)]
    assert all(p == (255, 255, 255) for p in inner)  # nothing drawn inside
    assert _near(_rgb(rows[c][0]), _rgb(ci.OFF_BORDER), 30)  # border on the left edge
    assert not any(_near(p, _rgb(ACCENT), 40) for p in _pixels(rows))


@pytest.mark.parametrize("state", ["off_disabled", "on_disabled"])
def test_disabled_boxes_are_pale_grey(state):
    size = ci.box_size(1.5)
    px = _pixels(ci.render(size, *ci.colours(ACCENT, "#1d4ed8")[state], bg="#f3f4f6"))
    assert all(min(p) >= 0xc0 for p in px)  # nothing darker than pale grey
    assert not any(_near(p, _rgb(ACCENT), 60) for p in px)


def test_state_order_matches_ttk_first_match():
    assert ci.image_for({"selected"}) == "on"
    assert ci.image_for({"selected", "active"}) == "on_active"
    assert ci.image_for({"selected", "pressed", "active"}) == "on_active"
    assert ci.image_for(set()) == "off"
    assert ci.image_for({"active"}) == "off_active"
    assert ci.image_for({"focus"}) == "off"  # the focus ring is drawn around the text, not by the box
    assert ci.image_for({"selected", "focus"}) == "on"
    assert ci.image_for({"disabled"}) == "off_disabled"
    assert ci.image_for({"disabled", "selected"}) == "on_disabled"
    assert ci.image_for({"disabled", "selected", "active"}) == "on_disabled"


def test_ticking_still_works_with_the_new_box(app):
    w = app.chk_rename
    before = bool(app.var_rename.get())
    try:
        w.invoke()
        assert bool(app.var_rename.get()) is (not before)
        assert ("selected" in w.state()) is (not before)
    finally:
        app.var_rename.set(before)


def test_installing_again_keeps_the_first_images(app):
    """A style rebuilt for the same window (music-folder-organizer does it on a language change)
    must not swap in new images: the element keeps the first ones, so those must stay alive."""
    from tkinter import ttk

    first = app._check_images
    again = ci.install(ttk.Style(app.root), app.root, scale=app.scale, accent=ACCENT, accent_dark="#1d4ed8",
                       bg="#f3f4f6", gap=1)
    assert again is first
    assert ci.ELEMENT in _names(ttk.Style(app.root).layout("TCheckbutton"))
