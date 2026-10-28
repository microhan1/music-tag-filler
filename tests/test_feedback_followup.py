"""「의견 보내기」 series follow-up (2026-10-28): keyboard, tooltip, one page-language rule, README links.

No real browser, no network and no real key or mouse event: webbrowser.open is replaced,
conftest refuses any outside connection, and key/mouse handling is tested by running the
scripts Tk itself would run for the button's bind tags (fire() below) and tk_focusNext.
"""
from __future__ import annotations

import os
import re
import time
import urllib.parse
import webbrowser

import pytest

import i18n
import net
import prefs as prefs_mod
import update_check as uc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLUG = "musictag"
KO = "https://chaekgalpi.co.kr/tools/musictag?utm_source=app&utm_medium=feedback&v=0.2.4#feedback"
EN = "https://chaekgalpi.co.kr/en/tools/musictag?utm_source=app&utm_medium=feedback&v=0.2.4#feedback"
TIPS = {"ko": "안 되는 것·불편한 것·바라는 기능을 알려 주세요(브라우저가 열립니다)",
        "en": "Tell us what's broken or missing (opens your browser)",
        "ja": "不具合・ご要望をお知らせください（ブラウザが開きます）",
        "zh-CN": "告诉我们问题或建议（将打开浏览器）"}


# ------------------------------------------------------------ helpers
class Browser:
    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, url, *args, **kwargs):
        self.calls.append(url)
        return True


@pytest.fixture
def browser(monkeypatch):
    b = Browser()
    monkeypatch.setattr(webbrowser, "open", b)
    return b


def _subst(script: str, widget, keysym: str, char: str) -> str:
    """Fill a binding script's %-fields the way Tk would for one event on `widget`."""
    values = {"W": widget._w, "K": keysym, "A": "{%s}" % char, "%": "%", "T": "2", "E": "0", "D": "0"}
    return re.sub(r"%(.)", lambda m: values.get(m.group(1), "0"), script)


def fire(widget, *sequences: str, keysym: str = "??", char: str = "") -> None:
    """Run what Tk runs for one event on `widget`: for each bind tag in order, the script of
    the first of `sequences` bound there (most specific first), stopping at "break". Nothing
    goes through Windows, so the user's own typing and mouse are never touched."""
    tk_ = widget.tk
    for tag in tk_.splitlist(tk_.call("bindtags", widget._w)):
        for seq in sequences:
            script = tk_.call("bind", tag, seq)
            if script:
                code = int(tk_.call("catch", _subst(str(script), widget, keysym, char), "_fire_err"))
                if code == 1:
                    raise RuntimeError(tk_.getvar("_fire_err"))
                if code == 3:  # break
                    return
                break


def pump(app, ms: int) -> None:
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        app.root.update()
        time.sleep(0.01)


def switch_lang(app, code):
    app.var_lang.set(i18n.LANG_NAMES[code])
    app._on_lang()


@pytest.fixture(scope="module")
def module_app():
    """One real App for the module, shown off-screen (Tk lays out and moves focus only among
    shown widgets), with no settings written, no online probe and no update check."""
    import gui

    before = i18n.current_lang()
    mp = pytest.MonkeyPatch()
    mp.setattr(i18n, "save_settings", lambda data: None)
    mp.setattr(prefs_mod, "save", lambda *a, **k: None)
    mp.setattr(prefs_mod, "load", lambda: prefs_mod.Prefs())
    mp.setattr(gui.App, "_probe_online", lambda self: None)
    mp.setattr(net, "APP_VERSION", "0.2.4")
    real_check = uc.check_async
    mp.setattr(uc, "check_async", lambda *a, **k: True)
    i18n.set_lang("ko", persist=False)
    a = gui.App()
    mp.setattr(uc, "check_async", real_check)
    a.root.geometry(f"+-5000+-5000")
    a.root.update()
    yield a
    a.tip_feedback.hide()
    a._closing = True
    a._thumb_pool.shutdown(wait=False, cancel_futures=True)
    a.covers.close()
    a.root.destroy()
    mp.undo()
    i18n.set_lang(before, persist=False)


@pytest.fixture
def app(module_app, browser):
    a = module_app
    a.tip_feedback.hide()
    switch_lang(a, "ko")
    if a._feedback_win is not None and a._feedback_win.winfo_exists():
        a._feedback_win.destroy()
    a._feedback_win = None
    a.btn_feedback.state(["!focus", "!pressed"])
    a.root.minsize(a.px(960), a.px(700))
    a.root.geometry(f"{a.px(1100)}x{a.px(760)}+-5000+-5000")
    a.root.update()
    yield a
    a.tip_feedback.hide()


# ------------------------------------------------------------ a. keyboard
def test_tab_reaches_the_button_after_the_update_option(app):
    assert app.chk_update.tk_focusNext() is app.btn_feedback
    assert app.btn_feedback.tk_focusPrev() is app.chk_update  # Shift+Tab goes back


def test_tab_leaves_the_button_forward_and_back(app):
    nxt, prv = app.btn_feedback.tk_focusNext(), app.btn_feedback.tk_focusPrev()
    assert nxt is not app.btn_feedback and prv is not app.btn_feedback
    assert nxt.tk_focusPrev() is app.btn_feedback


def test_the_tab_binding_moves_focus_with_tk_focus_next(app):
    """Tab and Shift+Tab are Tk's standard <<NextWindow>>/<<PrevWindow>> bindings
    (tk_focusNext/tk_focusPrev); running them moves Tk's focus onto and off the button."""
    tk_ = app.root.tk
    assert "<Key-Tab>" in str(tk_.call("event", "info", "<<NextWindow>>"))
    assert "tk_focusNext" in str(tk_.call("bind", "all", "<<NextWindow>>"))
    assert "tk_focusPrev" in str(tk_.call("bind", "all", "<<PrevWindow>>"))
    for tag in (app.btn_feedback._w, "TButton"):
        assert not str(tk_.call("bind", tag, "<Key-Tab>")) and not str(tk_.call("bind", tag, "<<NextWindow>>"))

    def focused():
        return str(tk_.call("focus", "-lastfor", app.root._w))

    fire(app.chk_update, "<<NextWindow>>")
    assert focused() == app.btn_feedback._w
    fire(app.btn_feedback, "<<PrevWindow>>")
    assert focused() == app.chk_update._w
    fire(app.chk_update, "<<NextWindow>>")
    fire(app.btn_feedback, "<<NextWindow>>")
    assert focused() == app.btn_feedback.tk_focusNext()._w


@pytest.mark.parametrize("seq, keysym, char", [("<Key-Return>", "Return", "\r"),
                                               ("<Key-KP_Enter>", "KP_Enter", "\r"),
                                               ("<Key-space>", "space", " ")])
def test_enter_and_space_open_the_page_once(app, browser, seq, keysym, char):
    fire(app.btn_feedback, seq, "<KeyPress>", keysym=keysym, char=char)
    app.root.update()
    assert browser.calls == [KO]


@pytest.mark.parametrize("code, expected", [("en", EN), ("ja", EN), ("zh-CN", EN), ("ko", KO)])
def test_enter_follows_the_language(app, browser, code, expected):
    switch_lang(app, code)
    fire(app.btn_feedback, "<Key-Return>", keysym="Return", char="\r")
    assert browser.calls == [expected]


@pytest.mark.parametrize("seq, keysym, char", [("<Key-a>", "a", "a"), ("<Key-x>", "x", "x"),
                                               ("<Key-Escape>", "Escape", "\x1b"),
                                               ("<Key-BackSpace>", "BackSpace", "\b"),
                                               ("<Key-Delete>", "Delete", ""), ("<Key-F1>", "F1", ""),
                                               ("<Key-Up>", "Up", ""), ("<Key-Down>", "Down", ""),
                                               ("<Key-1>", "1", "1"), ("<Key-hangul>", "hangul", "")])
def test_other_keys_do_nothing(app, browser, seq, keysym, char):
    fire(app.btn_feedback, seq, "<KeyPress>", keysym=keysym, char=char)
    app.root.update()
    assert browser.calls == []
    assert app._feedback_win is None


def test_focus_border_shows_and_size_stays(app):
    btn = app.btn_feedback
    style = __import__("tkinter.ttk", fromlist=["Style"]).Style(app.root)
    assert btn.cget("style") == "Feedback.TButton"
    off = [style.lookup("Feedback.TButton", opt, ["!focus"]) for opt in ("bordercolor", "lightcolor", "darkcolor")]
    on = [style.lookup("Feedback.TButton", opt, ["focus"]) for opt in ("bordercolor", "lightcolor", "darkcolor")]
    import gui

    assert on == [gui.ACCENT] * 3 and all(o != gui.ACCENT for o in off)
    btn.state(["!focus"])
    app.root.update_idletasks()
    size_off = (btn.winfo_reqwidth(), btn.winfo_reqheight())
    btn.state(["focus"])
    app.root.update_idletasks()
    assert btn.instate(["focus"])
    assert (btn.winfo_reqwidth(), btn.winfo_reqheight()) == size_off
    btn.state(["!focus"])
    assert not btn.instate(["focus"])


def test_feedback_style_is_the_small_button_otherwise(app):
    from tkinter import ttk

    style = ttk.Style(app.root)
    for opt in ("font", "padding"):
        assert str(style.lookup("Feedback.TButton", opt)) == str(style.lookup("Small.TButton", opt))


# ------------------------------------------------------------ b. tooltip
def tip_text(app) -> str:
    return app.tip_feedback.label.cget("text")


def test_hover_shows_the_tip_after_the_delay(app):
    fire(app.btn_feedback, "<Enter>")
    assert app.tip_feedback.tip is None  # not at once
    pump(app, app.tip_feedback.DELAY_MS + 250)
    tip = app.tip_feedback.tip
    assert tip is not None and tip.winfo_exists() and tip.winfo_ismapped()
    assert tip_text(app) == TIPS["ko"]
    assert 400 <= app.tip_feedback.DELAY_MS <= 500


def test_leaving_hides_the_tip(app):
    fire(app.btn_feedback, "<Enter>")
    pump(app, app.tip_feedback.DELAY_MS + 250)
    assert app.tip_feedback.tip is not None
    fire(app.btn_feedback, "<Leave>")
    assert app.tip_feedback.tip is None


def test_leaving_before_the_delay_shows_nothing(app):
    fire(app.btn_feedback, "<Enter>")
    pump(app, 150)
    fire(app.btn_feedback, "<Leave>")
    pump(app, app.tip_feedback.DELAY_MS + 250)
    assert app.tip_feedback.tip is None


def test_click_hides_the_tip_and_opens_once(app, browser):
    fire(app.btn_feedback, "<Enter>")
    pump(app, app.tip_feedback.DELAY_MS + 250)
    assert app.tip_feedback.tip is not None
    fire(app.btn_feedback, "<ButtonPress-1>", "<ButtonPress>", "<Button>")
    assert app.tip_feedback.tip is None
    fire(app.btn_feedback, "<ButtonRelease-1>", "<ButtonRelease>")
    app.root.update()
    assert browser.calls == [KO]
    assert app.tip_feedback.tip is None


def test_enter_key_while_the_tip_is_up_hides_it(app, browser):
    app.tip_feedback.show()
    fire(app.btn_feedback, "<Key-Return>", keysym="Return", char="\r")
    assert app.tip_feedback.tip is None and browser.calls == [KO]


@pytest.mark.parametrize("code", i18n.LANGS)
def test_tip_text_in_every_language(code):
    strings = i18n._I18n._load_file(code)
    assert strings["feedback_tip"] == TIPS[code]


def test_tip_texts_differ_and_are_not_empty():
    texts = [i18n._I18n._load_file(code)["feedback_tip"] for code in i18n.LANGS]
    assert all(s.strip() for s in texts) and len(set(texts)) == len(texts) == 4


@pytest.mark.parametrize("code", i18n.LANGS)
def test_tip_shown_in_the_screen_language(app, code):
    switch_lang(app, code)
    app.tip_feedback.show()
    assert tip_text(app) == TIPS[code]


@pytest.mark.parametrize("code", i18n.LANGS)
def test_tip_is_one_line_in_every_language(app, code):
    """At the old wrap width the Japanese tip left a lone "）" on a second line."""
    switch_lang(app, code)
    app.tip_feedback.show()
    label = app.tip_feedback.label
    assert app.font_small.measure(TIPS[code]) <= int(label.cget("wraplength"))
    assert label.winfo_reqheight() < 2 * app.font_small.metrics("linespace")


def test_language_switch_changes_a_tip_that_is_up(app):
    app.tip_feedback.show()
    for code in ("en", "ja", "zh-CN", "ko"):
        switch_lang(app, code)
        assert app.tip_feedback.tip is not None
        assert tip_text(app) == TIPS[code]


def test_language_switch_without_a_tip_shows_none(app):
    switch_lang(app, "en")
    assert app.tip_feedback.tip is None


def test_tip_only_once_while_hovering(app):
    fire(app.btn_feedback, "<Enter>")
    fire(app.btn_feedback, "<Enter>")
    pump(app, app.tip_feedback.DELAY_MS + 250)
    tips = [w for w in app.btn_feedback.winfo_children() if w.winfo_class() == "Toplevel"]
    assert len(tips) == 1


def test_hidden_window_shows_no_tip(app):
    app.root.withdraw()
    try:
        app.tip_feedback.show()
        assert app.tip_feedback.tip is None
    finally:
        app.root.deiconify()
        app.root.geometry("+-5000+-5000")
        app.root.update()


def _geometry_of(tip):
    m = re.search(r"([+-]-?\d+)([+-]-?\d+)$", tip.geometry())
    return int(m.group(1)), int(m.group(2))


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("code", i18n.LANGS)
def test_tip_stays_inside_the_window_and_the_screen(app, code, side):
    """Smallest window flush against the screen's left or right edge: the note is inside both."""
    root = app.root
    switch_lang(app, code)
    root.geometry(f"{app.px(960)}x{app.px(700)}" + ("+0+0" if side == "left" else "-0+0"))
    root.update()
    app.tip_feedback.show()
    tip = app.tip_feedback.tip
    x, y = _geometry_of(tip)
    w, h = tip.winfo_reqwidth(), tip.winfo_reqheight()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    assert 0 <= x and x + w <= sw and 0 <= y and y + h <= sh, (x, y, w, h, sw, sh)
    left, right = root.winfo_rootx(), root.winfo_rootx() + root.winfo_width()
    assert left <= x and x + w <= right, (x, w, left, right)
    assert y >= app.btn_feedback.winfo_rooty() + app.btn_feedback.winfo_height()  # under the button
    assert tip_text(app) == TIPS[code]


# ------------------------------------------------------------ c. one page-language rule
KOREAN = ["ko", "KO", "Ko", "ko-KR", "ko_KR", "KO-kr", " ko "]
OTHER = ["en", "ja", "zh", "zh-CN", "zh_CN", "zh-TW", "fr", "de", "EN", "en-US", "xx", "ja-JP", "es", "kor",
         "k", "-ko", "o"]
EMPTY = [None, "", "  ", "\t"]


@pytest.mark.parametrize("lang", KOREAN)
def test_korean_codes_get_the_korean_page(lang):
    assert uc.is_korean(lang)
    assert uc.feedback_url(SLUG, "0.2.4", lang) == KO


@pytest.mark.parametrize("lang", OTHER)
def test_every_other_code_gets_the_english_page(lang):
    assert not uc.is_korean(lang)
    assert uc.feedback_url(SLUG, "0.2.4", lang) == EN


@pytest.mark.parametrize("lang", EMPTY)
def test_no_language_follows_the_default_screen_language(lang, monkeypatch):
    assert uc.DEFAULT_LANG == i18n.DEFAULT_LANG == "en"
    assert uc.feedback_url(SLUG, "0.2.4", lang) == EN
    monkeypatch.setattr(uc, "DEFAULT_LANG", "ko")  # the rule reads the default, not a fixed answer
    assert uc.feedback_url(SLUG, "0.2.4", lang) == KO


@pytest.mark.parametrize("lang", KOREAN + OTHER + EMPTY)
def test_address_shape_for_every_code(lang):
    url = uc.feedback_url(SLUG, "0.2.4", lang)
    parts = urllib.parse.urlsplit(url)
    assert (parts.scheme, parts.hostname, parts.fragment) == ("https", "chaekgalpi.co.kr", "feedback")
    assert parts.path == ("/tools/musictag" if uc.is_korean(lang) else "/en/tools/musictag")
    assert urllib.parse.parse_qs(parts.query) == {"utm_source": ["app"], "utm_medium": ["feedback"], "v": ["0.2.4"]}


PAGE_KO = "https://chaekgalpi.co.kr/tools/musictag"
PAGE_EN = "https://chaekgalpi.co.kr/en/tools/musictag"


@pytest.mark.parametrize("lang", KOREAN + OTHER + EMPTY)
def test_update_page_follows_the_same_rule(lang):
    info = uc.interpret({"updateAvailable": True, "latest": "9.9.9", "url": PAGE_KO, "urlEn": PAGE_EN}, "0.2.4")
    page = uc.link_for(info, lang)
    assert page == (PAGE_KO if uc.is_korean(lang) else PAGE_EN)
    # the feedback box and the update page always agree on the language
    assert urllib.parse.urlsplit(uc.feedback_url(SLUG, "1", lang)).path == urllib.parse.urlsplit(page).path


@pytest.mark.parametrize("lang", OTHER + EMPTY)
def test_update_page_without_an_english_page_is_korean(lang):
    info = uc.interpret({"updateAvailable": True, "latest": "9.9.9", "url": PAGE_KO}, "0.2.4")
    assert uc.link_for(info, lang) == PAGE_KO


def test_old_language_lists_are_gone():
    assert not hasattr(uc, "FEEDBACK_EN")


@pytest.mark.parametrize("code, page", [("ko", PAGE_KO), ("en", PAGE_EN), ("ja", PAGE_EN), ("zh-CN", PAGE_EN)])
def test_update_button_in_the_window_uses_the_rule(app, browser, code, page):
    switch_lang(app, code)
    app.var_update_check.set(True)
    app._on_update_result(uc.UpdateInfo("9.9.9", "0.2.4", PAGE_KO, PAGE_EN), True)
    app._update_open()
    assert browser.calls == [page]


# ------------------------------------------------------------ d. README links
READMES = {"README.md": "ko", "README.en.md": "en", "README.ja.md": "ja", "README.zh-CN.md": "zh-CN"}
UTM = "?utm_source=github&utm_medium=referral&utm_campaign=tool_cta&utm_content=musictag"
MD_LINK = re.compile(r"\]\(([^)\s]+)\)")
BAD_END = re.compile(r"[)）가-힣ㄱ-ㆎ，。、：；！？」』]$")


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def links(text):
    return MD_LINK.findall(text)


@pytest.mark.parametrize("name, code", READMES.items())
def test_readme_feedback_link(name, code):
    hrefs = [h for h in links(read(name)) if "chaekgalpi.co.kr" in h and h.endswith("#feedback")]
    expected = PAGE_KO if code == "ko" else PAGE_EN
    assert hrefs == [expected + "#feedback"]


@pytest.mark.parametrize("name, code", READMES.items())
def test_readme_tool_page_link(name, code):
    hrefs = [h for h in links(read(name)) if "chaekgalpi.co.kr" in h and not h.endswith("#feedback")]
    if code == "ko":
        assert hrefs == [PAGE_KO]
    else:
        assert hrefs == [PAGE_EN + UTM]


@pytest.mark.parametrize("name", list(READMES) + ["docs/releases/v0.2.5.md"])
def test_no_link_swallows_the_next_character(name):
    text = read(name)
    bad = [h for h in links(text) if BAD_END.search(h)]
    assert bad == []
    # an address written bare (not as [text](address)) would be auto-linked with whatever follows
    bare = re.sub(r"\]\([^)\s]+\)", "](…)", text)
    bare = re.sub(r"`[^`]*`", "", bare)
    assert re.findall(r"https?://\S+", bare) == []


def test_bad_end_check_catches_the_known_mistakes():
    for href in ("https://chaekgalpi.co.kr/tools/musictag#feedback)", "https://x.kr/a이",
                 "https://x.kr/a，", "https://x.kr/a。", "https://x.kr/a）"):
        assert BAD_END.search(href)
    assert not BAD_END.search(PAGE_EN + "#feedback")


@pytest.mark.parametrize("name", ["README.ja.md", "README.zh-CN.md"])
def test_korean_only_notes_kept(name):
    """The web service being Korean-only is a fact the READMEs may state; nothing here removes it."""
    text = read(name)
    assert "chaekgalpi.co.kr/en/tools/musictag#feedback" in text


# ------------------------------------------------------------ f. no network
def test_whole_follow_up_touches_no_network(app, browser, network_blocked, update_server_blocked):
    for code in ("ko", "en", "ja", "zh-CN"):
        switch_lang(app, code)
        fire(app.btn_feedback, "<Enter>")
        pump(app, app.tip_feedback.DELAY_MS + 150)
        fire(app.btn_feedback, "<Key-Return>", keysym="Return", char="\r")
        fire(app.btn_feedback, "<Key-space>", keysym="space", char=" ")
        fire(app.btn_feedback, "<ButtonPress-1>", "<ButtonPress>")
        fire(app.btn_feedback, "<ButtonRelease-1>", "<ButtonRelease>")
    app.root.update()
    assert len(browser.calls) == 12
    assert network_blocked == []
    assert update_server_blocked.calls == []
