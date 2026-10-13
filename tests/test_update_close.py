"""Closing the window while the update check is still waiting must not kill the process.

Runs the real App in a child process three times: a fake server answer takes 3 s, the
window closes at 2 s (the request started at 1.5 s), and the child stays alive until the
worker thread has finished and let go of its references. No real request, no settings
written."""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHILD = textwrap.dedent(r"""
    import os, sys, threading, time, gc
    sys.path.insert(0, {root!r}); os.chdir({root!r})
    import i18n; i18n.init("en"); i18n.set_lang("en", persist=False)
    import prefs as prefs_mod
    prefs_mod.save = lambda *a, **k: None
    prefs_mod.load = lambda: prefs_mod.Prefs()
    import net
    net.online = lambda *a, **k: True
    import update_check
    orig = update_check.check_async

    def slow(slug, version):
        time.sleep(3.0)
        return {{"latest": "9.9.9", "updateAvailable": True, "url": "https://chaekgalpi.co.kr/tools/musictag"}}

    update_check.check_async = lambda *a, **k: orig(*a, fetcher=slow, **k)
    import gui
    real_init = gui.App.__init__

    def init(self, *a, **k):
        real_init(self, *a, **k)
        self.root.after(2000, self._on_close)

    gui.App.__init__ = init
    gui.launch()
    for t in threading.enumerate():
        if t.name == "update-check":
            t.join(10)
    gc.collect()
    time.sleep(0.5)
    print("SURVIVED", flush=True)
""")


@pytest.mark.parametrize("attempt", [1, 2, 3])
def test_closing_during_the_check_does_not_crash(attempt):
    pytest.importorskip("tkinter")
    proc = subprocess.run([sys.executable, "-c", CHILD.format(root=ROOT)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60, cwd=ROOT,
                          env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    assert proc.returncode == 0, proc.stderr[-800:]
    assert "SURVIVED" in proc.stdout
    assert "Tcl_AsyncDelete" not in proc.stderr
