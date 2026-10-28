"""「의견 보내기」: the button only opens the tool page's feedback box in the browser.

No real browser and no network here: webbrowser.open is replaced for every test, conftest
refuses any outside connection, and the App runs with saving switched off.
"""
from __future__ import annotations

import socket
import urllib.parse
import webbrowser

import pytest

import i18n
import net
import prefs as prefs_mod
import update_check as uc

KO = "https://chaekgalpi.co.kr/tools/musictag?utm_source=app&utm_medium=feedback&v=0.2.4#feedback"
EN = "https://chaekgalpi.co.kr/en/tools/musictag?utm_source=app&utm_medium=feedback&v=0.2.4#feedback"
LABELS = {"ko": "의견 보내기", "en": "Send feedback", "ja": "ご意見を送る", "zh-CN": "发送反馈"}


def v_of(url: str) -> list[str]:
    return urllib.parse.parse_qs(urllib.parse.urlsplit(url).query, keep_blank_values=True).get("v", [])


# ------------------------------------------------------------ a. address
@pytest.mark.parametrize("lang, expected", [("ko", KO), ("en", EN), ("ja", EN), ("zh-CN", EN)])
def test_address_for_each_language(lang, expected):
    assert uc.feedback_url("musictag", "0.2.4", lang) == expected


@pytest.mark.parametrize("lang", [None, "", "fr", "de", "zh-TW", "zh", "xx-YY", "  "])
def test_other_or_missing_language_gets_the_english_page(lang):
    """Only Korean gets the Korean page (2026-10-28 series rule); no language means the
    program's default screen language, English."""
    assert uc.feedback_url("musictag", "0.2.4", lang) == EN


@pytest.mark.parametrize("lang, expected", [("EN", EN), ("En", EN), ("JA", EN), ("zh-cn", EN), ("ZH-CN", EN),
                                            ("zh_CN", EN), ("KO", KO), (" en ", EN)])
def test_language_code_case_does_not_matter(lang, expected):
    assert uc.feedback_url("musictag", "0.2.4", lang) == expected


@pytest.mark.parametrize("lang", ["ko", "en", "ja", "zh-CN", None])
@pytest.mark.parametrize("version", ["0.2.4", "", None])
def test_address_shape(lang, version):
    url = uc.feedback_url("musictag", version, lang)
    assert url.startswith("https://chaekgalpi.co.kr/")
    assert url.endswith("#feedback")
    parts = urllib.parse.urlsplit(url)
    assert parts.scheme == "https" and parts.hostname == "chaekgalpi.co.kr"
    assert parts.fragment == "feedback"
    q = urllib.parse.parse_qs(parts.query)
    assert q["utm_source"] == ["app"] and q["utm_medium"] == ["feedback"]
    assert parts.path in ("/tools/musictag", "/en/tools/musictag")


def test_address_uses_only_constants():
    """Nothing from settings or the server: the same inputs give the same address."""
    assert uc.FEEDBACK_PAGE.startswith(uc.SITE)
    assert uc.feedback_url("musictag", "1", "ko") == uc.feedback_url("musictag", "1", "ko")


# ------------------------------------------------------------ b. version
@pytest.mark.parametrize("version, encoded", [("0.2.1", "0.2.1"), ("v0.2.1", "v0.2.1"),
                                              ("1.0.0-beta+3", "1.0.0-beta%2B3")])
def test_version_values(version, encoded):
    url = uc.feedback_url("musictag", version, "ko")
    assert f"&v={encoded}#feedback" in url
    assert v_of(url) == [version]


@pytest.mark.parametrize("version", ["", None, " ", "\t"])
def test_empty_version_leaves_v_out(version):
    url = uc.feedback_url("musictag", version, "ko")
    assert "v=" not in url
    assert url == "https://chaekgalpi.co.kr/tools/musictag?utm_source=app&utm_medium=feedback#feedback"


@pytest.mark.parametrize("version", ["1.0 beta", "1&utm_source=evil", "1#x", "버전 0.2", "a=b?c/d",
                                     "1%20", "+plus+", " 0.2.4 ", "v1.0.0-rc.1+build.5&x=#y 한글"])
def test_odd_versions_are_encoded_and_read_back(version):
    url = uc.feedback_url("musictag", version, "en")
    parts = urllib.parse.urlsplit(url)
    assert parts.fragment == "feedback"
    assert parts.path == "/en/tools/musictag"
    q = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
    assert q == {"utm_source": ["app"], "utm_medium": ["feedback"], "v": [version]}
    assert url.count("#") == 1 and url.count("?") == 1
    assert all(ord(c) < 128 and c != " " for c in url)


def test_running_version_is_the_app_version():
    assert v_of(uc.feedback_url("musictag", net.APP_VERSION, "ko")) == [net.APP_VERSION]


# ------------------------------------------------------------ the App
class Browser:
    """webbrowser.open stand-in: records the address, then answers or raises."""

    def __init__(self, result=True):
        self.calls: list[str] = []
        self.result = result

    def __call__(self, url, *args, **kwargs):
        self.calls.append(url)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


@pytest.fixture
def browser(monkeypatch):
    b = Browser()
    monkeypatch.setattr(webbrowser, "open", b)
    return b


@pytest.fixture(scope="module")
def module_app():
    """One real App for the module, hidden, with no settings written, no online probe and no
    clipboard. (A new Tk per test intermittently failed with "Can't find a usable tk.tcl".)"""
    import gui

    before = i18n.current_lang()
    mp = pytest.MonkeyPatch()
    mp.setattr(i18n, "save_settings", lambda data: None)
    mp.setattr(prefs_mod, "save", lambda *a, **k: None)
    mp.setattr(prefs_mod, "load", lambda: prefs_mod.Prefs())
    mp.setattr(gui.App, "_probe_online", lambda self: None)
    mp.setattr(net, "APP_VERSION", "0.2.4")
    clip: list[str] = []
    mp.setattr(gui.tk.Misc, "clipboard_clear", lambda self, **kw: clip.clear())
    mp.setattr(gui.tk.Misc, "clipboard_append", lambda self, s, **kw: clip.append(s))
    checks: list = []
    real_check = uc.check_async
    # the start-up check is only recorded: conftest's guard is not active outside a test
    mp.setattr(uc, "check_async", lambda root, slug, version, *a, **k: checks.append((slug, version)) or True)
    i18n.set_lang("ko", persist=False)
    a = gui.App()
    a.root.withdraw()
    a.clip, a.checks = clip, checks
    mp.setattr(uc, "check_async", real_check)
    yield a
    a._closing = True
    a._thumb_pool.shutdown(wait=False, cancel_futures=True)
    a.covers.close()
    a.root.destroy()
    mp.undo()
    i18n.set_lang(before, persist=False)


@pytest.fixture
def app(module_app, browser):
    """The module's App back in its starting state: Korean, no notice, no address window."""
    a = module_app
    switch_lang(a, "ko")
    if a._feedback_win is not None and a._feedback_win.winfo_exists():
        a._feedback_win.destroy()
    a._feedback_win = None
    a._hide_update_notice()
    a.var_update_check.set(True)
    a.clip.clear()
    a.root.update_idletasks()
    return a


def switch_lang(app, code):
    app.var_lang.set(i18n.LANG_NAMES[code])
    app._on_lang()


def state(app):
    return (app._status_key, dict(app._status_kwargs), list(app.files), app.current, app.lbl_status.cget("text"), prefs_mod.Prefs(**vars(app.prefs)), app.var_update_check.get(), app._update_info)


# ------------------------------------------------------------ c. the button's callback
def test_button_opens_the_page_once(app, browser):
    app.btn_feedback.invoke()
    assert browser.calls == [KO]


@pytest.mark.parametrize("code, expected", [("en", EN), ("ja", EN), ("zh-CN", EN), ("ko", KO)])
def test_language_switch_changes_the_next_address(app, browser, code, expected):
    app.btn_feedback.invoke()
    switch_lang(app, code)
    app.btn_feedback.invoke()
    assert browser.calls == [KO, expected]


def test_each_click_opens_once(app, browser):
    for _ in range(3):
        app.open_feedback()
    assert browser.calls == [KO] * 3


def test_opened_page_shows_no_dialog(app, browser):
    app.open_feedback()
    assert getattr(app, "_feedback_win", None) is None


# ------------------------------------------------------------ d. no browser
@pytest.mark.parametrize("result", [False, None, webbrowser.Error("no runnable browser"), OSError(5, "denied"),
                                    RuntimeError("odd")])
def test_failure_shows_the_address_and_keeps_going(app, browser, result):
    browser.result = result
    before = state(app)
    app.open_feedback()  # must not raise
    assert browser.calls == [KO]
    win = app._feedback_win
    assert win.winfo_exists()
    assert win.title() == "의견 보내기"
    entries = [w for w in all_children(win) if w.winfo_class() == "Entry"]
    assert len(entries) == 1 and entries[0].get() == KO
    assert str(entries[0].cget("state")) == "readonly"
    texts = [w.cget("text") for w in all_children(win) if w.winfo_class() == "TLabel"]
    assert any("브라우저를 열지 못했습니다" in s for s in texts)
    assert state(app) == before
    assert app.root.winfo_exists()


def test_failure_address_follows_the_language(app, browser):
    browser.result = False
    switch_lang(app, "ja")
    app.open_feedback()
    win = app._feedback_win
    assert win.title() == "ご意見を送る"
    assert [w.get() for w in all_children(win) if w.winfo_class() == "Entry"] == [EN]


def test_copy_button_copies_the_address(app, browser):
    browser.result = False
    app.open_feedback()
    buttons = {w.cget("text"): w for w in all_children(app._feedback_win) if w.winfo_class() == "TButton"}
    buttons["복사"].invoke()
    assert app.clip == [KO]
    assert buttons["복사"].cget("text") == "복사됨"
    buttons["닫기"].invoke()
    assert not app._feedback_win.winfo_exists()


def test_failure_then_success(app, browser):
    browser.result = False
    app.open_feedback()
    app._feedback_win.destroy()
    browser.result = True
    app._feedback_win = None
    app.open_feedback()
    assert browser.calls == [KO, KO]
    assert app._feedback_win is None


def all_children(w):
    out = []
    for c in w.winfo_children():
        out.append(c)
        out.extend(all_children(c))
    return out


# ------------------------------------------------------------ e. texts
NEW_KEYS = ("btn_feedback", "feedback_failed_title", "feedback_failed", "btn_copy", "btn_copied", "btn_close")


@pytest.mark.parametrize("code", i18n.LANGS)
def test_new_texts_exist_in_every_language(code):
    strings = i18n._I18n._load_file(code)
    for key in NEW_KEYS:
        assert isinstance(strings.get(key), str) and strings[key].strip(), (code, key)
    assert strings["btn_feedback"] == LABELS[code]


def test_language_files_have_the_same_keys():
    keys = {code: set(i18n._I18n._load_file(code)) for code in i18n.LANGS}
    assert all(k == keys["en"] for k in keys.values())


def test_button_text_follows_the_language(app):
    assert app.btn_feedback.cget("text") == LABELS["ko"]
    for code in ("en", "ja", "zh-CN", "ko"):
        switch_lang(app, code)
        assert app.btn_feedback.cget("text") == LABELS[code]


def test_button_sits_in_the_header_next_to_the_update_option(app):
    assert app.btn_feedback.master is app.chk_update.master
    info, chk = app.btn_feedback.grid_info(), app.chk_update.grid_info()
    assert int(info["row"]) == int(chk["row"]) and int(info["column"]) == int(chk["column"]) + 1


@pytest.mark.parametrize("code", i18n.LANGS)
def test_drop_hint_shortens_in_a_narrow_window_and_comes_back(app, code):
    """The button takes room from the header: the hint ends in "…" instead of running into
    the next label, and is whole again when the window is wide."""
    switch_lang(app, code)
    full = i18n.t("drop_hint")
    root = app.root
    root.minsize(1, 1)
    root.geometry(f"{app.px(820)}x{app.px(700)}+-5000+-5000")  # shown off-screen: a hidden window is not laid out
    root.deiconify()
    try:
        root.update()
        short = app.lbl_drop.cget("text")
        assert short != full
        if short:  # with no room at all (English at this width) the hint is simply left out
            assert short.endswith("…") and full.startswith(short[:-1].rstrip())
        assert app.font_body.measure(short) <= app.lbl_drop.winfo_width()
        root.geometry(f"{app.px(1600)}x{app.px(820)}+-5000+-5000")
        root.update()
        assert app.lbl_drop.cget("text") == full
    finally:
        root.withdraw()
        root.minsize(app.px(960), app.px(700))


# ------------------------------------------------------------ f. nothing else changed
def test_update_notice_still_opens_the_update_page(app, browser):
    app.var_update_check.set(True)
    info = uc.UpdateInfo("9.9.9", "0.2.4", "https://chaekgalpi.co.kr/tools/musictag",
                         "https://chaekgalpi.co.kr/en/tools/musictag")
    app._on_update_result(info, True)
    assert app._update_info is info
    app.open_feedback()
    assert app._update_info is info  # feedback leaves the notice alone
    app._update_open()
    assert browser.calls == [KO, "https://chaekgalpi.co.kr/tools/musictag"]
    assert app._update_info is None


def test_update_check_still_scheduled_once_at_start(app, browser):
    import gui

    assert app.checks == [("musictag", "0.2.4")]
    assert gui.UPDATE_SLUG == "musictag"
    assert browser.calls == []  # starting the window opens no page


def test_update_toggle_hides_the_notice_but_not_the_button(app, browser):
    app._on_update_result(uc.UpdateInfo("9.9.9", "0.2.4", "https://chaekgalpi.co.kr/tools/musictag"), True)
    app.var_update_check.set(False)
    app._on_update_toggle()
    assert app._update_info is None
    app.btn_feedback.invoke()
    assert browser.calls == [KO]


def test_cli_help_unchanged(capsys):
    import main

    before = i18n.current_lang()
    try:
        with pytest.raises(SystemExit) as e:
            main.main(["--help", "--lang", "en"])
        assert e.value.code == 0
        out = capsys.readouterr().out
        for opt in ("--auto", "--country", "--rename", "--overwrite", "--lyrics", "--sound", "--undo",
                    "--no-recurse", "--lang", "--gui"):
            assert opt in out
        assert "feedback" not in out.lower()
    finally:
        i18n.set_lang(before, persist=False)


def test_cli_version_flag_still_absent(capsys):
    """The CLI never had --version; this change does not add one (argparse rejects it)."""
    import main

    before = i18n.current_lang()
    try:
        with pytest.raises(SystemExit) as e:
            main.main(["--version", "--lang", "en"])
        assert e.value.code == 2
    finally:
        i18n.set_lang(before, persist=False)


# ------------------------------------------------------------ g. no network
def test_guard_catches_a_connection(network_blocked):
    """The zero below means something: the guard does see an outside connection."""
    with pytest.raises(OSError):
        socket.create_connection(("example.com", 80), timeout=1)
    assert network_blocked == [("example.com", 80)]
    network_blocked.clear()


def test_whole_feedback_flow_touches_no_network(app, browser, network_blocked, update_server_blocked):
    for code in ("ko", "en", "ja", "zh-CN"):
        switch_lang(app, code)
        app.open_feedback()
    for result in (False, webbrowser.Error("x"), OSError("y")):
        browser.result = result
        app.open_feedback()
        app._feedback_win.destroy()
    app.root.update()
    assert len(browser.calls) == 7
    assert network_blocked == []
    assert update_server_blocked.calls == []
