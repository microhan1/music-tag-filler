"""Close the exe the moment its window is up, while requests and Pillow are still loading in
the background: it must end cleanly, quickly, and leave no _MEI* folder behind.

    python tests/exe_startup_check.py <exe> [runs=3]

Dead proxy, own TEMP (see measure_startup.py). The exe writes its settings.json next to
itself when the window closes, so never point this at the exe the user runs.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import measure_startup as ms  # noqa: E402

WM_CLOSE = 0x0010


def once(exe: str) -> tuple[int, float, list[str]]:
    root = tempfile.mkdtemp(prefix="mtf_exe_close_")
    tmp = os.path.join(root, "tmp")
    os.makedirs(tmp)
    env = ms.offline_env(dict(os.environ, TEMP=tmp, TMP=tmp))
    proc = subprocess.Popen([exe], env=env)
    try:
        t0 = time.perf_counter()
        main = []
        while time.perf_counter() - t0 < 60 and not main:
            main = [w for w in ms.windows_of(ms.family(proc.pid)) if w["caption"]]
            time.sleep(0.01)
        assert main, "no window came up"
        ms.user32.PostMessageW(main[0]["hwnd"], WM_CLOSE, 0, 0)
        t1 = time.perf_counter()
        rc = proc.wait(timeout=30)
        took = time.perf_counter() - t1
        time.sleep(0.5)
        left = [d for d in os.listdir(tmp) if d.startswith("_MEI")]
        return rc, took, left
    finally:
        if proc.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
            time.sleep(1)
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    exe = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    bad = 0
    for k in range(1, n + 1):
        rc, took, left = once(exe)
        ok = rc == 0 and not left and took < 10
        bad += not ok
        print(f"run {k}: exit code {rc} · closed in {took:.2f}s · _MEI left {len(left)} · {'ok' if ok else 'FAIL'}",
              flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
