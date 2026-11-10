"""Start-up work of 2026-11-10 (hub instruction "splash"): requests and Pillow are imported after
the window is up, files added while they still load give the same result, and the exe's
start-up picture is closed exactly once, after the window is painted.

    python -m pytest tests/test_startup.py -q

Each probe runs in a fresh process: in the pytest process requests and Pillow are long imported,
so "not loaded yet" cannot be seen there. A slow import is made with a finder put in front of
sys.meta_path that sleeps. Nothing is written (prefs.save is a no-op), the update server is
guarded (tests/update_guard.py), the online probe is stubbed, and the process runs behind a
dead proxy besides.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

import startup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(ROOT, "samples")
DEAD_PROXY = "http://127.0.0.1:9"

HEAD = r"""
import json, os, sys, threading, time, types
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.chdir(ROOT)
HEAVY = ("requests", "PIL.Image", "PIL.ImageDraw", "PIL.ImageTk")

def heavy():
    return {m: m in sys.modules for m in HEAVY}

class Slow:
    def find_spec(self, name, path=None, target=None):
        if name in ("requests", "PIL.Image"):
            time.sleep(1.5)
        return None

class Broken:
    def find_spec(self, name, path=None, target=None):
        if name == "requests":
            raise ImportError("boom requests")
        return None

def out(**kw):
    print("RESULT " + json.dumps(kw, ensure_ascii=False), flush=True)

def fake_splash():
    calls = []
    mod = types.ModuleType("pyi_splash")
    mod.calls = calls
    mod.close = lambda: calls.append(1)
    sys.modules["pyi_splash"] = mod
    return mod

def quiet_app():
    # no settings written, no update server, no online probe, no search: the window alone
    import i18n; i18n.init("en"); i18n.set_lang("en", persist=False)
    import prefs as prefs_mod
    prefs_mod.save = lambda *a, **k: None
    prefs_mod.load = lambda: prefs_mod.Prefs()
    import update_check, update_guard
    update_guard.install(update_check, update_guard.make_opener())
    import net
    net.online = lambda *a, **k: True
    import pipeline
    pipeline.search_text = lambda *a, **k: pipeline.SearchResult([], [])
    import gui
    return gui

ROOT_HEAVY_AT_START = heavy()
"""


def run(body: str, timeout: float = 120, **values) -> dict:
    tmp = tempfile.mkdtemp(prefix="mtf_startup_test_")
    try:
        script = os.path.join(tmp, "probe.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write(f"ROOT = {ROOT!r}\n")
            for k, v in values.items():
                f.write(f"{k} = {v!r}\n")
            f.write(HEAD + body)
        env = dict(os.environ, PYTHONIOENCODING="utf-8", HTTP_PROXY=DEAD_PROXY, HTTPS_PROXY=DEAD_PROXY)
        env.pop("NO_PROXY", None)
        p = subprocess.run([sys.executable, script], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=env, timeout=timeout)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    lines = [ln for ln in p.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, f"no result rc={p.returncode}\n{p.stdout[-800:]}\n{p.stderr[-1500:]}"
    assert p.returncode == 0, f"rc={p.returncode}\n{p.stderr[-1500:]}"
    return json.loads(lines[-1][7:])


NOT_LOADED = {"requests": False, "PIL.Image": False, "PIL.ImageDraw": False, "PIL.ImageTk": False}
LOADED = {k: True for k in NOT_LOADED}


@pytest.fixture
def songs():
    """Writable copies of the three sample files."""
    tmp = tempfile.mkdtemp(prefix="mtf_startup_songs_")
    out = []
    for name in ("sample-a.mp3", "sample-b.flac", "sample-c.ogg"):
        shutil.copy(os.path.join(SAMPLES, name), tmp)
        out.append(os.path.join(tmp, name))
    yield out
    shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- the stand-in itself (in process)
def test_lazy_module_imports_on_first_attribute_and_only_once(monkeypatch):
    loads = []
    real = startup.importlib.import_module

    def counting(name):
        loads.append(name)
        return real(name)

    monkeypatch.setattr(startup.importlib, "import_module", counting)
    m = startup.LazyModule("json")
    try:
        assert not m.loaded
        assert m.dumps({"a": 1}) == '{"a": 1}'
        assert m.loaded and m.load() is json
        assert m.loads("[1]") == [1]
        assert loads == ["json"]
    finally:
        startup._LAZY.remove(m)


def test_lazy_module_dunder_probe_does_not_import():
    m = startup.LazyModule("json")
    try:
        with pytest.raises(AttributeError):
            m.__wrapped__
        assert not m.loaded
    finally:
        startup._LAZY.remove(m)


def test_build_script_names_every_lazily_imported_module():
    """startup.lazy() imports by name at run time, which PyInstaller cannot see: each such module
    must be a --hidden-import in build.bat, or the exe ships without it (LESSONS D12)."""
    import re

    import gui, net  # noqa: F401,E401 - registers their LazyModules

    with open(os.path.join(ROOT, "build.bat"), encoding="utf-8") as f:
        hidden = set(re.findall(r'--hidden-import\s+"([^"]+)"', f.read()))
    lazy = {m._name for m in startup._LAZY}
    assert lazy <= hidden, f"missing from build.bat: {sorted(lazy - hidden)}"


# ---------------------------------------------------------------- deferred imports (fresh processes)
def test_import_does_not_load_heavy_modules():
    r = run("import main, gui, pipeline, net\nout(start=ROOT_HEAVY_AT_START, after=heavy())\n")
    assert r == {"start": NOT_LOADED, "after": NOT_LOADED}


def test_window_comes_up_without_heavy_modules_and_cover_box_has_its_size():
    r = run(r'''
gui = quiet_app()
app = gui.App()
app.root.update()
state = heavy()
size = app.px(gui.COVER_PX)
shown = app.lbl_cover.cget("image")
w = int(app.root.call("image", "width", shown))
h = int(app.root.call("image", "height", shown))
ready = app._placeholder_ready
app.root.destroy()
out(state=state, size=size, w=w, h=h, ready=ready)
''')
    assert r["state"] == NOT_LOADED
    assert (r["w"], r["h"]) == (r["size"], r["size"])
    assert r["ready"] is False


def test_first_attribute_use_loads_the_real_module():
    r = run(r'''
import net, gui
before = heavy()
s = net.requests.Session()
import requests, PIL.Image
ok = isinstance(s, requests.Session) and net.requests.load() is requests
im = gui.Image.new("RGB", (2, 2))
out(before=before, ok=ok, im=im.size, real=gui.Image.load() is PIL.Image, after=heavy())
''')
    assert r["before"] == NOT_LOADED
    assert r["ok"] is True and r["real"] is True and r["im"] == [2, 2]
    assert r["after"]["requests"] and r["after"]["PIL.Image"]


def test_many_threads_wait_for_one_load():
    r = run(r'''
sys.meta_path.insert(0, Slow())
import net, gui
errors, sizes = [], []
def use():
    try:
        net.requests.Session().close()
        sizes.append(gui.Image.new("RGB", (3, 1)).size)
    except Exception as e:
        errors.append(repr(e))
threads = [threading.Thread(target=use) for _ in range(8)]
t0 = time.perf_counter()
[t.start() for t in threads]
[t.join() for t in threads]
out(errors=errors, n=len(sizes), seconds=time.perf_counter() - t0)
''')
    assert r["errors"] == [] and r["n"] == 8
    assert r["seconds"] < 6, "every thread imported for itself"


def test_broken_load_is_reported_at_first_use_and_preload_survives():
    r = run(r'''
sys.meta_path.insert(0, Broken())
import startup, net
startup.preload_heavy()
try:
    net.session()
    kind = "none"
except ImportError as e:
    kind = "ImportError" if "boom" in str(e) else repr(e)
out(kind=kind)
''')
    assert r == {"kind": "ImportError"}


# ---------------------------------------------------------------- files added while still loading
FILES_BODY = r'''
gui = quiet_app()
if SLOW:
    sys.meta_path.insert(0, Slow())
else:
    import startup; startup.load_heavy()
app = gui.App()
app.root.update()
if SLOW:
    threading.Thread(target=gui.startup.preload_heavy, kwargs={"done": lambda: app._ui(app._finish_placeholder)},
                     daemon=True).start()
added_before_load = not heavy()["PIL.Image"]
app.add_paths(SONGS)
ticks = []
def tick():
    ticks.append(time.perf_counter())
    app.root.after(30, tick)
tick()
def watch():
    if app._busy() or not all(f.info is not None or f.error for f in app.files) or not app._placeholder_ready:
        app.root.after(50, watch)
    else:
        app.root.after(200, app.root.quit)
watch()
app.root.after(60000, app.root.quit)
app.root.mainloop()
gaps = [b - a for a, b in zip(ticks, ticks[1:])]
files = [dict(name=f.name(), error=f.error, title=f.values.get("title"), artist=f.values.get("artist"),
              fmt=f.info.fmt if f.info else None, has_cover=f.has_cover) for f in app.files]
shown = app.lbl_cover.cget("image")
state = dict(added_before_load=added_before_load, busy=app._busy(), files=files, n_ticks=len(ticks),
             max_gap=max(gaps), ready=app._placeholder_ready, cover_is_placeholder=shown == str(app._placeholder),
             heavy=heavy())
app.root.destroy()
out(**state)
'''


def test_files_added_while_libraries_still_load_give_the_same_result(songs):
    slow = run(FILES_BODY, SLOW=True, SONGS=songs)
    ready = run(FILES_BODY, SLOW=False, SONGS=songs)
    assert slow["added_before_load"] is True and ready["added_before_load"] is False
    assert slow["busy"] is False and ready["busy"] is False
    assert slow["files"] == ready["files"], (slow["files"], ready["files"])
    assert [f["error"] for f in slow["files"]] == [None, None, None]
    assert slow["ready"] is True and slow["cover_is_placeholder"] is True
    assert slow["heavy"] == LOADED
    assert slow["n_ticks"] > 30, "the window stopped while waiting"


# ---------------------------------------------------------------- the start-up picture
LAUNCH_WRAP = r'''
gui = quiet_app()
splash = fake_splash()
Real = gui.App
seen, state = {}, {}
class App(Real):
    def __init__(self, initial_files=None):
        super().__init__(initial_files)
        seen["app"] = self
        self.root.after(20000, self.root.destroy)   # ends the run even if the picture is never closed
gui.App = App
def on_close():
    app = seen["app"]
    try:
        state["viewable"] = bool(app.root.winfo_viewable())
    except Exception as e:      # close_splash swallows exceptions; keep it here
        state["error"] = repr(e)
    state["heavy_at_close"] = heavy()
    splash.calls.append(1)
    app.root.after(CLOSE_AFTER, app.root.destroy)
splash.close = on_close
'''


def test_launch_closes_splash_once_after_the_window_is_painted():
    r = run("CLOSE_AFTER = 300\n" + LAUNCH_WRAP + r'''
gui.launch()
out(calls=len(splash.calls), **state)
''')
    assert r == {"calls": 1, "viewable": True, "heavy_at_close": NOT_LOADED}


def test_launch_preloads_in_the_background_and_finishes_the_cover_box():
    r = run("CLOSE_AFTER = 15000\n" + LAUNCH_WRAP + r'''
def check():
    app = seen["app"]
    if app._placeholder_ready and gui.startup.heavy_loaded():
        state["ready"] = True
        state["shown_is_placeholder"] = app.lbl_cover.cget("image") == str(app._placeholder)
        state["heavy"] = heavy()
        app.root.destroy()
    else:
        app.root.after(50, check)
real_init = App.__init__
def init(self, *a, **k):
    real_init(self, *a, **k)
    self.root.after(50, check)
App.__init__ = init
gui.launch()
out(ready=state.get("ready", False), shown=state.get("shown_is_placeholder"), heavy=state.get("heavy"))
''')
    assert r == {"ready": True, "shown": True, "heavy": LOADED}


def test_splash_is_closed_when_the_window_cannot_be_made():
    r = run(r'''
gui = quiet_app()
splash = fake_splash()
class Bad:
    def __init__(self, *a, **k):
        raise RuntimeError("no window")
gui.App = Bad
import main
try:
    main.main([])
    kind = "none"
except RuntimeError:
    kind = "RuntimeError"
out(kind=kind, calls=len(splash.calls))
''')
    assert r == {"kind": "RuntimeError", "calls": 1}


def test_console_run_closes_splash_before_working():
    r = run(r'''
splash = fake_splash()
import main
rc = main.main(["--undo", os.path.join(ROOT, "no-such-file.mp3")])
out(rc=rc, calls=len(splash.calls), heavy=heavy())
''')
    assert r == {"rc": 2, "calls": 1, "heavy": NOT_LOADED}


def test_close_splash_is_silent_without_pyinstaller_and_closes_once():
    r = run(r'''
import startup
startup.close_splash()                 # no pyi_splash at all
startup._splash_closed = False
splash = fake_splash()
startup.close_splash()
startup.close_splash()                 # the second call is a no-op
startup._splash_closed = False
def boom():
    raise ConnectionError("already closed")
splash.close = boom
startup.close_splash()
out(calls=len(splash.calls))
''')
    assert r == {"calls": 1}


def test_closing_the_window_during_the_background_load_exits_cleanly():
    r = run("CLOSE_AFTER = 50\nsys.meta_path.insert(0, Slow())\n" + LAUNCH_WRAP + r'''
t0 = time.perf_counter()
gui.launch()
out(fast=time.perf_counter() - t0 < 8)
''', timeout=40)
    assert r == {"fast": True}
