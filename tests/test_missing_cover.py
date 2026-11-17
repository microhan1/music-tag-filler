"""「표지 없는 파일만」 (only files without a cover), 2026-11-17.

With the option on, files that already carry a cover are left out when files or folders are
added (drop, Add files, Add folder, subfolders too), and the status line says how many were
skipped. The cover test is the window's own (FileState.has_cover: tags.read_file found a
front cover); the other tags do not count. The CLI has --only-missing-cover.

Every file here is made for the test in tmp_path from the committed samples: no user music.
The App is real, shown off-screen, writes no settings and never goes online; searching is
replaced by an empty answer (conftest refuses any outside connection anyway).
"""
from __future__ import annotations

import hashlib
import io
import os
import shutil
import time

import pytest

import i18n
import pipeline
import prefs as prefs_mod
import tags
import update_check as uc
from tests.test_tags import FIXTURES, _ensure_fixtures

# (relative path, sample it is copied from, has a cover, has title/artist/album)
LIBRARY = (
    ("01-cover-tagged.mp3", "sample-a.mp3", True, True),
    ("02-nocover-tagged.mp3", "sample-a.mp3", False, True),
    ("03-cover.flac", "sample-b.flac", True, False),
    ("04-nocover.flac", "sample-b.flac", False, False),
    (os.path.join("disc2", "05-cover.ogg"), "sample-c.ogg", True, False),
    (os.path.join("disc2", "06-nocover-tagged.ogg"), "sample-c.ogg", False, True),
    (os.path.join("disc2", "07-cover-tagged.m4a"), "sample-d.m4a", True, True),
    (os.path.join("disc2", "08-nocover.m4a"), "sample-d.m4a", False, False),
)
BROKEN = "09-broken.mp3"  # not audio: cannot be read, so it cannot be judged


def _png(size: int = 64, color=(30, 90, 200)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (size, size), color).save(buf, "PNG")
    return buf.getvalue()


def build_library(root: str) -> str:
    """A small album folder with a subfolder: covers on half the files, in all four formats."""
    _ensure_fixtures()
    cover, mime = tags.prepare_cover(_png(300, (200, 30, 30)))
    for rel, sample, with_cover, tagged in LIBRARY:
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        shutil.copy(os.path.join(FIXTURES, sample), path)
        base = os.path.splitext(os.path.basename(rel))[0]
        text = tags.Tags(title=f"Title {base}", artist="Test Artist", album="Test Album") if tagged else tags.Tags()
        if with_cover or tagged:
            tags.write_file(path, text, cover if with_cover else None, mime)
    with open(os.path.join(root, BROKEN), "wb") as f:
        f.write(b"this is not an mp3 file" * 10)
    with open(os.path.join(root, "notes.txt"), "w", encoding="utf-8") as f:
        f.write("not music")
    return root


def names(paths) -> list[str]:
    return sorted(os.path.basename(p) for p in paths)


NO_COVER_ALL = sorted(os.path.basename(r) for r, _s, c, _t in LIBRARY if not c)
NO_COVER_TOP = sorted(os.path.basename(r) for r, _s, c, _t in LIBRARY if not c and os.sep not in r)


@pytest.fixture
def library(tmp_path) -> str:
    return build_library(str(tmp_path / "album"))


def _hashes(root: str) -> dict[str, str]:
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            p = os.path.join(dirpath, name)
            with open(p, "rb") as f:
                out[p] = hashlib.sha256(f.read()).hexdigest()
    return out


# ------------------------------------------------------------ the filter itself
def test_library_is_what_the_tests_assume(library):
    for rel, _s, with_cover, tagged in LIBRARY:
        info = tags.read_file(os.path.join(library, rel))
        assert (info.cover is not None) == with_cover, rel
        assert bool(info.tags.title) == tagged, rel


def test_keeps_files_without_a_cover_in_every_format_and_subfolder(library):
    files = tags.collect_files([library], recurse=True)
    kept, skipped = pipeline.split_missing_cover(files)
    assert skipped == 4
    assert names(p for p, _i in kept) == sorted(NO_COVER_ALL + [BROKEN])
    readable = {os.path.basename(p): i for p, i in kept if i is not None}
    assert sorted(i.fmt for i in readable.values()) == ["FLAC", "M4A", "MP3", "OGG"]
    assert all(i.cover is None for i in readable.values())


def test_without_subfolders_only_the_top_folder_is_judged(library):
    files = tags.collect_files([library], recurse=False)
    kept, skipped = pipeline.split_missing_cover(files)
    assert skipped == 2
    assert names(p for p, _i in kept) == sorted(NO_COVER_TOP + [BROKEN])


def test_a_file_with_every_tag_but_no_cover_is_kept(library):
    kept, _ = pipeline.split_missing_cover(tags.collect_files([library]))
    info = dict((os.path.basename(p), i) for p, i in kept)["02-nocover-tagged.mp3"]
    assert (info.tags.title, info.tags.artist, info.tags.album) == ("Title 02-nocover-tagged", "Test Artist",
                                                                      "Test Album")


def test_an_unreadable_file_is_kept_unjudged_not_dropped(library):
    kept, _ = pipeline.split_missing_cover([os.path.join(library, BROKEN)])
    assert kept == [(os.path.join(library, BROKEN), None)]


def test_checking_changes_no_file(library):
    before = _hashes(library)
    pipeline.split_missing_cover(tags.collect_files([library]))
    assert _hashes(library) == before
    assert not [p for p in before if p.endswith(".tagbak.json")]


def test_progress_and_cancel(library):
    import threading

    files = tags.collect_files([library])
    seen: list = []
    cancel = threading.Event()

    def progress(idx, name):
        seen.append((idx, name))
        if idx == 3:
            cancel.set()

    kept, skipped = pipeline.split_missing_cover(files, cancel=cancel, on_progress=progress)
    assert [i for i, _n in seen] == [1, 2, 3]
    assert seen[0][1] == os.path.basename(files[0])
    assert len(kept) + skipped == 3


# ------------------------------------------------------------ settings
def test_setting_is_off_by_default_and_read_with_its_type(monkeypatch):
    assert prefs_mod.Prefs().only_missing_cover is False
    for raw, expected in (({}, False), ({"only_missing_cover": True}, True), ({"only_missing_cover": False}, False),
                          ({"only_missing_cover": "yes"}, False), ({"only_missing_cover": 1}, False)):
        monkeypatch.setattr(i18n, "load_settings", lambda raw=raw: dict(raw))
        assert prefs_mod.load().only_missing_cover is expected, raw


def test_setting_round_trips_through_the_file(monkeypatch):
    stored: dict = {"lang": "ko", "acoustid_key": ""}
    monkeypatch.setattr(i18n, "load_settings", lambda: dict(stored))
    monkeypatch.setattr(i18n, "save_settings", lambda data: (stored.clear(), stored.update(data)))
    p = prefs_mod.load()
    p.only_missing_cover = True
    prefs_mod.save(p)
    assert stored["only_missing_cover"] is True and stored["lang"] == "ko"
    assert prefs_mod.load().only_missing_cover is True


# ------------------------------------------------------------ CLI
@pytest.fixture
def cli(monkeypatch):
    """main.main with searching answered empty and settings neither read nor written."""
    import main

    searched: list[str] = []
    empty = pipeline.SearchResult([], [])
    monkeypatch.setattr(pipeline, "search_text", lambda query, *a, **k: searched.append(query) or empty)
    monkeypatch.setattr(pipeline, "search_sound", lambda path, *a, **k: searched.append(path) or empty)
    monkeypatch.setattr(prefs_mod, "load", lambda: prefs_mod.Prefs())
    monkeypatch.setattr(i18n, "save_settings", lambda data: None)
    before = i18n.current_lang()
    yield main, searched
    i18n.set_lang(before, persist=False)


def test_cli_auto_skips_covered_files_and_prints_the_count(cli, library, capsys):
    main, _searched = cli
    code = main.main([library, "--only-missing-cover", "--auto", "--lang", "ko"])
    out, err = capsys.readouterr()
    i18n.set_lang("ko", persist=False)
    line = i18n.t("msg_cover_skipped", count=4)
    assert out.count(line) == 2  # first, and again after the summary
    assert out.rstrip().endswith(line)
    for rel, _s, with_cover, _t in LIBRARY:
        assert (os.path.basename(rel) in out) != with_cover, rel
    assert i18n.t("err_open_failed", name=BROKEN) in err
    assert code == 1  # nothing found for the kept files, one unreadable


def test_cli_without_the_option_goes_through_every_file(cli, library, capsys):
    main, _searched = cli
    main.main([library, "--auto", "--lang", "ko"])
    out, _err = capsys.readouterr()
    for rel, *_ in LIBRARY:
        assert os.path.basename(rel) in out, rel
    i18n.set_lang("ko", persist=False)
    assert i18n.t("msg_cover_skipped", count=4) not in out


def test_cli_no_recurse_with_the_option(cli, library, capsys):
    main, _searched = cli
    main.main([library, "--only-missing-cover", "--no-recurse", "--auto", "--lang", "en"])
    out, _err = capsys.readouterr()
    i18n.set_lang("en", persist=False)
    assert out.count(i18n.t("msg_cover_skipped", count=2)) == 2
    assert "02-nocover-tagged.mp3" in out and "04-nocover.flac" in out
    assert "06-nocover-tagged.ogg" not in out and "01-cover-tagged.mp3" not in out


def test_cli_when_every_file_has_a_cover(cli, tmp_path, capsys):
    main, searched = cli
    root = build_library(str(tmp_path / "album"))
    os.remove(os.path.join(root, BROKEN))
    for rel, _s, with_cover, _t in LIBRARY:
        if not with_cover:
            os.remove(os.path.join(root, rel))
    code = main.main([root, "--only-missing-cover", "--auto", "--lang", "ko"])
    out, _err = capsys.readouterr()
    i18n.set_lang("ko", persist=False)
    assert out.strip() == i18n.t("msg_all_have_cover", count=4)  # one line, no separate skip count
    assert searched == [] and code == 0


def test_cli_help_lists_the_option_in_every_language(cli, capsys):
    main, _searched = cli
    for code in i18n.LANGS:
        with pytest.raises(SystemExit):
            main.main(["--lang", code, "--help"])
        out, _err = capsys.readouterr()
        i18n.set_lang(code, persist=False)
        flat = " ".join(out.split())  # argparse wraps long help lines
        assert "--only-missing-cover" in flat
        assert " ".join(i18n.t("cli_only_missing_cover").split()) in flat


def test_cli_undo_ignores_the_option(cli, library, capsys):
    main, _searched = cli
    main.main([library, "--only-missing-cover", "--undo", "--lang", "en"])
    out, _err = capsys.readouterr()
    i18n.set_lang("en", persist=False)
    assert "01-cover-tagged.mp3" in out  # "no backup" is reported for covered files too: nothing filtered
    assert i18n.t("msg_cover_skipped", count=4) not in out


# ------------------------------------------------------------ window
def pump(app, ms: int) -> None:
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        app.root.update()
        time.sleep(0.01)


def wait_idle(app, timeout: float = 30.0) -> None:
    """Run the real event loop until the worker is done. The worker hands its updates over
    with root.after from its own thread, which Tk only accepts while mainloop runs
    (update() in a loop is not enough: "main thread is not in main loop", LESSONS D10)."""
    end = time.monotonic() + timeout
    settle = {"at": None}

    def check():
        now = time.monotonic()
        if app._busy() and now < end:
            settle["at"] = None
        elif settle["at"] is None:
            settle["at"] = now  # done: let the worker's last after(0) calls run
        elif now - settle["at"] > 0.15 or now >= end:
            app.root.quit()
            return
        app.root.after(10, check)

    app.root.after(10, check)
    app.root.mainloop()
    assert not app._busy(), "worker did not finish"


@pytest.fixture(scope="module")
def module_app():
    import gui

    before = i18n.current_lang()
    mp = pytest.MonkeyPatch()
    mp.setattr(i18n, "save_settings", lambda data: None)
    saved: list = []
    mp.setattr(prefs_mod, "save", lambda p, *a, **k: saved.append(p.only_missing_cover))
    mp.setattr(prefs_mod, "load", lambda: prefs_mod.Prefs())
    mp.setattr(gui.App, "_probe_online", lambda self: None)
    real_check = uc.check_async
    mp.setattr(uc, "check_async", lambda *a, **k: True)
    i18n.set_lang("ko", persist=False)
    a = gui.App()
    mp.setattr(uc, "check_async", real_check)
    a.root.geometry("+-5000+-5000")
    pump(a, 300)
    a.saved_prefs = saved
    yield a
    a._closing = True
    a._thumb_pool.shutdown(wait=False, cancel_futures=True)
    a.covers.close()
    a.root.destroy()
    mp.undo()
    i18n.set_lang(before, persist=False)


@pytest.fixture
def app(module_app, monkeypatch):
    """The module's App with an empty list, Korean, the option off, empty search answers and
    every dialog answered without showing it (an error dialog fails the test)."""
    import gui

    a = module_app
    a.var_lang.set(i18n.LANG_NAMES["ko"])
    a._on_lang()
    a.clear_files()
    a.var_only_missing_cover.set(False)
    a.saved_prefs.clear()
    searched: list[str] = []
    monkeypatch.setattr(gui.pipeline, "search_text",
                        lambda query, *x, **k: searched.append(query) or pipeline.SearchResult([], []))
    a.searched = searched
    a.answers = {"recurse": True, "cover_all": True}
    asked: list[str] = []

    def askyesno(title, message, **k):
        asked.append(message)
        return a.answers["recurse"] if message == i18n.t("warn_recurse") else a.answers["cover_all"]

    a.asked = asked
    monkeypatch.setattr(gui.messagebox, "askyesno", askyesno)
    errors: list = []
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *x, **k: errors.append(x))
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda *x, **k: errors.append(x))
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *x, **k: None)
    yield a
    assert errors == []
    wait_idle(a)
    a.clear_files()


def listed(app) -> list[str]:
    return sorted(s.name() for s in app.files)


def test_option_box_is_off_at_start_and_sits_under_the_cover_buttons(app):
    assert app.var_only_missing_cover.get() is False
    assert app.chk_only_missing_cover.master is app.btn_cover.master
    assert app.chk_only_missing_cover.winfo_manager() == "pack"  # shown with no file, so it can be set before a drop
    assert app.chk_only_missing_cover.cget("text") == i18n.t("opt_only_missing_cover")


def test_box_label_says_search_in_every_language():
    """2026-11-17 (사장님): 「표지 없는 파일만 넣기」 → 「표지 없는 파일만 검색」. The setting key and
    the CLI flag keep their names so old settings files still work."""
    want = {"ko": "표지 없는 파일만 검색", "en": "Search only files without a cover",
            "zh-CN": "只搜索无封面的文件", "ja": "ジャケットのない曲だけ検索"}
    before = i18n.current_lang()
    try:
        for lang, text in want.items():
            i18n.set_lang(lang, persist=False)
            assert i18n.t("opt_only_missing_cover") == text
            assert "넣기" not in i18n.t("tip_only_missing_cover")
    finally:
        i18n.set_lang(before, persist=False)
    assert "only_missing_cover" in prefs_mod.Prefs.__dataclass_fields__


def test_ticking_the_box_saves_the_setting(app):
    app.chk_only_missing_cover.invoke()
    assert app.var_only_missing_cover.get() is True
    assert app.prefs.only_missing_cover is True and app.saved_prefs == [True]
    app.chk_only_missing_cover.invoke()
    assert app.prefs.only_missing_cover is False and app.saved_prefs == [True, False]


def test_option_off_lists_every_file_as_before(app, library):
    app.add_paths([library])
    wait_idle(app)
    assert listed(app) == sorted([os.path.basename(r) for r, *_ in LIBRARY] + [BROKEN])
    assert i18n.t("msg_cover_skipped", count=4) not in app.lbl_status.cget("text")


def test_adding_a_folder_lists_only_files_without_a_cover(app, library):
    app.var_only_missing_cover.set(True)
    before = _hashes(library)
    app.add_paths([library])
    wait_idle(app)
    assert listed(app) == sorted(NO_COVER_ALL + [BROKEN])
    status = app.lbl_status.cget("text")
    assert status.startswith(i18n.t("msg_cover_skipped", count=4))
    assert i18n.t("msg_batch_done", auto=0, total=5) in status
    # every kept file was searched once with what the filter read (the broken one has nothing)
    assert len(app.searched) == 4
    broken = next(s for s in app.files if s.name() == BROKEN)
    assert broken.error == "err_open_failed"
    assert all(not s.has_cover and s.info is not None for s in app.files if s is not broken)
    assert _hashes(library) == before


def test_without_subfolders_only_the_top_folder(app, library):
    app.var_only_missing_cover.set(True)
    app.answers["recurse"] = False
    app.add_paths([library])
    wait_idle(app)
    assert listed(app) == sorted(NO_COVER_TOP + [BROKEN])
    assert app.lbl_status.cget("text").startswith(i18n.t("msg_cover_skipped", count=2))


def test_dropped_files_are_filtered_too(app, library):
    app.var_only_missing_cover.set(True)
    picked = [os.path.join(library, r) for r in ("01-cover-tagged.mp3", "02-nocover-tagged.mp3", "03-cover.flac")]
    app.add_paths(picked)  # what a drop and Add files call
    wait_idle(app)
    assert listed(app) == ["02-nocover-tagged.mp3"]
    assert app.current is not None and app.current.name() == "02-nocover-tagged.mp3"
    assert app.lbl_status.cget("text").startswith(i18n.t("msg_cover_skipped", count=2))


def test_a_folder_where_every_file_has_a_cover(app, tmp_path):
    root = build_library(str(tmp_path / "full"))
    os.remove(os.path.join(root, BROKEN))
    for rel, _s, with_cover, _t in LIBRARY:
        if not with_cover:
            os.remove(os.path.join(root, rel))
    app.var_only_missing_cover.set(True)
    app.add_paths([root])
    wait_idle(app)
    assert app.files == [] and app.searched == []
    assert app.lbl_status.cget("text") == i18n.t("msg_all_have_cover", count=4)


def test_files_already_in_the_list_are_not_checked_again(app, library):
    app.add_paths([os.path.join(library, "01-cover-tagged.mp3")])  # option off: a covered file comes in
    wait_idle(app)
    app.var_only_missing_cover.set(True)
    app.add_paths([library])
    wait_idle(app)
    assert listed(app) == sorted(["01-cover-tagged.mp3"] + NO_COVER_ALL + [BROKEN])
    assert app.lbl_status.cget("text").startswith(i18n.t("msg_cover_skipped", count=3))


def test_skip_count_follows_the_language(app, library):
    app.var_lang.set(i18n.LANG_NAMES["ja"])
    app._on_lang()
    app.var_only_missing_cover.set(True)
    app.add_paths([library])
    wait_idle(app)
    assert app.lbl_status.cget("text").startswith("ジャケットのある 4 曲はスキップ")


def test_then_one_cover_for_the_whole_list_and_save_all(app, library, tmp_path):
    """The flow the option is for: list the files missing a cover, give one of them a cover,
    「이 표지를 목록 전체에」, 「전체 저장」 → every listed file now carries it."""
    app.var_only_missing_cover.set(True)
    app.add_paths([library])
    wait_idle(app)
    assert app.btn_cover_all.winfo_manager()  # the button shows once there are several files
    image = tmp_path / "front.png"
    image.write_bytes(_png(500, (10, 160, 60)))
    app._set_cover_from_file(str(image))
    app.apply_cover_to_all()
    assert app.lbl_status.cget("text") == i18n.t("msg_cover_applied", count=3)  # 4 readable files, minus the shown one
    app.save_all()
    wait_idle(app)
    for name in NO_COVER_ALL:
        rel = next(r for r, *_ in LIBRARY if os.path.basename(r) == name)
        path = os.path.join(library, rel)
        info = tags.read_file(path)
        assert info.cover is not None, name
        assert os.path.exists(path + ".tagbak.json"), name
    # the covered files were never listed, so they were not touched
    for rel, _s, with_cover, _t in LIBRARY:
        if with_cover:
            assert not os.path.exists(os.path.join(library, rel) + ".tagbak.json"), rel
    # and the tags a file already had are still there
    info = tags.read_file(os.path.join(library, "02-nocover-tagged.mp3"))
    assert (info.tags.title, info.tags.artist) == ("Title 02-nocover-tagged", "Test Artist")


def test_cancel_while_checking_lists_nothing(app, library, monkeypatch):
    real = pipeline.split_missing_cover

    def slow(paths, **k):
        app.cancel_event.set()  # as if Cancel was pressed during the check
        return real(paths, **k)

    import gui

    monkeypatch.setattr(gui.pipeline, "split_missing_cover", slow)
    app.var_only_missing_cover.set(True)
    app.add_paths([library])
    wait_idle(app)
    assert app.files == []
    assert app.lbl_status.cget("text") == i18n.t("status_cancelled")


# ------------------------------------------------------------ nothing cut at the smallest window
def box(w):
    return (w.winfo_rootx(), w.winfo_rooty(), w.winfo_rootx() + w.winfo_width(), w.winfo_rooty() + w.winfo_height())


def inside(a, b) -> bool:
    return b[0] <= a[0] and a[2] <= b[2] and b[1] <= a[1] and a[3] <= b[3]


def show_files(app, n: int) -> None:
    import gui

    app.files = [gui.FileState(path=os.path.join("C:" + os.sep, "music", f"song-{i}.mp3")) for i in range(n)]
    app.lst_files.delete(0, "end")
    for _ in app.files:
        app.lst_files.insert("end", "")
    app._refresh_list()


@pytest.mark.parametrize("files", [0, 1, 2])
@pytest.mark.parametrize("code", ["ko", "en", "zh-CN", "ja"])
def test_option_is_whole_at_the_smallest_window(module_app, code, files):
    """One box on screen, whole, inside the top pane and its column, at the smallest window in every
    language: under the cover buttons with no file list (0 or 1 file), under the file list buttons
    once the list shows (2 files, the cover-all button shown too)."""
    app = module_app
    app.var_lang.set(i18n.LANG_NAMES[code])
    app._on_lang()
    show_files(app, files)
    min_w, min_h = app.root.minsize()
    app.root.geometry(f"{min_w}x{min_h}+-5000+-5000")
    app._fit_pending = True
    pump(app, 300)
    app._fit_top_pane()
    pump(app, 100)
    shown, hidden = app.chk_only_missing_cover, app.chk_only_missing_cover_list
    if files >= 2:
        shown, hidden = hidden, shown
    must = [shown, app.btn_cover] + ([app.btn_cover_all, app.btn_add, app.btn_add_dir, app.btn_clear] if files >= 2 else [])
    top = box(app.frm_top)
    problems = []
    if hidden.winfo_ismapped():
        problems.append(("both boxes shown",))
    for w in must:
        if not w.winfo_ismapped() or w.winfo_width() < w.winfo_reqwidth() or w.winfo_height() < w.winfo_reqheight():
            problems.append((str(w), "smaller than asked", w.winfo_width(), w.winfo_reqwidth()))
        if not inside(box(w), top):
            problems.append((str(w), "outside the top pane", box(w), top))
    if not inside(box(shown), box(shown.master)):
        problems.append(("box outside its column", box(shown), box(shown.master)))
    if files < 2 and box(shown)[1] < box(app.btn_cover)[3]:
        problems.append(("box above the cover button",))
    if files >= 2 and box(shown)[1] < box(app.btn_add)[3]:
        problems.append(("box above the file buttons",))
    show_files(app, 0)
    app.var_lang.set(i18n.LANG_NAMES["ko"])
    app._on_lang()
    assert problems == []


def test_both_boxes_are_one_setting(app):
    show_files(app, 2)
    app.chk_only_missing_cover_list.invoke()
    assert app.var_only_missing_cover.get() is True and app.prefs.only_missing_cover is True
    show_files(app, 1)
    assert app.chk_only_missing_cover.winfo_manager() == "pack"
    assert app.chk_only_missing_cover.instate(["selected"])
    app.chk_only_missing_cover.invoke()
    assert app.prefs.only_missing_cover is False and app.saved_prefs == [True, False]
    show_files(app, 0)


def test_a_list_adds_no_height_to_the_top_pane(app):
    """With a file list the cover column is the tallest; the box moved to the file column must not
    make the top pane ask for more than v0.2.7 did (the cover column's own height)."""
    show_files(app, 2)
    pump(app, 100)
    column = app.btn_cover.master
    assert app.frm_files.winfo_reqheight() <= column.winfo_reqheight()
    assert not app.chk_only_missing_cover.winfo_manager()
    show_files(app, 0)
