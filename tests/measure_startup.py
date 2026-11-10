"""Start the exe and time the start-up picture and the window (2026-11-10, hub instruction "splash").

    python tests/measure_startup.py <exe> [runs=3] [--shot picture.png]

- No internet: a dead proxy (HTTP_PROXY=HTTPS_PROXY=http://127.0.0.1:9), so neither the update
  check nor the online probe reaches a server (global rule 8). The exe is run where it is; its
  settings.json sits next to it, so never point this at the exe the user runs.
- TEMP/TMP go to a folder of their own, removed afterwards, so the _MEI* left by the forced
  kill at the end is ours and goes with it.
- Only windows of the started process (and its children) are looked at; a window the user has
  open is never counted. A window with a title bar (WS_CAPTION) is the program window, one
  without is the start-up picture (PyInstaller's splash is a borderless Tk window titled "tk").
- Taskbar entries: visible, unowned windows without WS_EX_TOOLWINDOW.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes

sys.stdout.reconfigure(encoding="utf-8")

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
user32.SetProcessDPIAware()

GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_CAPTION, WS_EX_TOOLWINDOW = 0x00C00000, 0x00000080
GW_OWNER = 4
user32.GetWindowLongW.restype = ctypes.c_long
user32.GetWindow.restype = wintypes.HWND
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE

DEAD_PROXY = "http://127.0.0.1:9"


def offline_env(base: dict | None = None) -> dict:
    env = dict(os.environ if base is None else base)
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env[key] = DEAD_PROXY
    for key in ("NO_PROXY", "no_proxy"):
        env.pop(key, None)
    return env


class PE(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]


def family(root_pid: int) -> set[int]:
    """root_pid and its descendants (the one-file exe starts a child process)."""
    snap = kernel32.CreateToolhelp32Snapshot(2, 0)
    pe = PE()
    pe.dwSize = ctypes.sizeof(PE)
    parents = {}
    ok = kernel32.Process32FirstW(snap, ctypes.byref(pe))
    while ok:
        parents[pe.th32ProcessID] = pe.th32ParentProcessID
        ok = kernel32.Process32NextW(snap, ctypes.byref(pe))
    kernel32.CloseHandle(snap)
    found = {root_pid}
    grew = True
    while grew:
        grew = False
        for pid, parent in parents.items():
            if parent in found and pid not in found:
                found.add(pid)
                grew = True
    return found


def windows_of(pids: set[int]) -> list[dict]:
    """Visible top-level windows owned by pids."""
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids:
            n = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            style = user32.GetWindowLongW(hwnd, GWL_STYLE)
            ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            out.append(dict(hwnd=hwnd, title=buf.value, pid=pid.value,
                            caption=bool((style & WS_CAPTION) == WS_CAPTION),
                            taskbar=not (ex & WS_EX_TOOLWINDOW) and not user32.GetWindow(hwnd, GW_OWNER),
                            size=(r.right - r.left, r.bottom - r.top)))
        return True

    user32.EnumWindows(cb, 0)
    return out


def shot(hwnd, path: str) -> None:
    """What is on screen (the splash is not DPI-aware, so PrintWindow would mis-scale it)."""
    from PIL import ImageGrab

    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    ImageGrab.grab((r.left, r.top, r.right, r.bottom), all_screens=True).save(path)


def measure(exe: str, shot_path: str | None = None, limit: float = 60.0, settle: float = 3.0) -> dict:
    root = tempfile.mkdtemp(prefix="mtf_measure_")
    tmp = os.path.join(root, "tmp")
    os.makedirs(tmp)
    env = offline_env(dict(os.environ, TEMP=tmp, TMP=tmp))
    t0 = time.perf_counter()
    proc = subprocess.Popen([exe], env=env)
    res = dict(splash=None, window=None, splash_gone=None, tasks_max=0, tasks_after=None, leftover=None, mei=0,
               title="")
    try:
        pids = family(proc.pid)
        last_family = 0.0
        settled = None
        while time.perf_counter() - t0 < limit:
            now = time.perf_counter() - t0
            if now - last_family > 0.1:
                pids = family(proc.pid)
                last_family = now
            ws = windows_of(pids)
            plain = [w for w in ws if not w["caption"]]
            main = [w for w in ws if w["caption"]]
            res["tasks_max"] = max(res["tasks_max"], sum(w["taskbar"] for w in ws))
            if plain and res["splash"] is None:
                res["splash"] = now
                res["splash_info"] = {k: plain[0][k] for k in ("title", "taskbar", "size")}
                if shot_path:
                    time.sleep(0.15)
                    shot(plain[0]["hwnd"], shot_path)
            if main and res["window"] is None:
                res["window"] = now
                res["title"] = main[0]["title"]
                settled = now
            if res["window"] is not None and not plain and res["splash_gone"] is None:
                res["splash_gone"] = now
            if settled is not None and now - settled > settle:  # what it looks like `settle` s after the window
                res["tasks_after"] = sum(w["taskbar"] for w in ws)
                res["leftover"] = len(plain)
                res["leftover_info"] = [{k: w[k] for k in ("title", "taskbar", "size")} for w in plain]
                break
            time.sleep(0.01)
        res["mei"] = len([d for d in os.listdir(tmp) if d.startswith("_MEI")])
    finally:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        time.sleep(1.0)
        shutil.rmtree(root, ignore_errors=True)  # the _MEI* left by the kill is only in here
    return res


def fmt(v) -> str:
    return f"{v:.2f}" if isinstance(v, float) else "-"


def main() -> None:
    args = list(sys.argv[1:])
    shot_path = None
    if "--shot" in args:
        i = args.index("--shot")
        shot_path = args[i + 1]
        del args[i:i + 2]
    exe = args[0]
    n = int(args[1]) if len(args) > 1 else 3
    print(f"{exe}  ({os.path.getsize(exe) / 1024 / 1024:.1f}MB)")
    print("run | splash (s) | window (s) | splash gone (s) | taskbar max | taskbar after | splash left | _MEI | title")
    rows = []
    for k in range(1, n + 1):
        r = measure(exe, shot_path if k == 1 else None)
        rows.append(r)
        print(f"{k} | {fmt(r['splash'])} | {fmt(r['window'])} | {fmt(r['splash_gone'])} | {r['tasks_max']} | "
              f"{r['tasks_after']} | {r['leftover']} | {r['mei']} | {r['title']}", flush=True)
        if r.get("splash_info"):
            print("   splash window:", r["splash_info"], flush=True)
        if r.get("leftover_info"):
            print("   still open without a title bar:", r["leftover_info"], flush=True)
    win = [r["window"] for r in rows if r["window"]]
    spl = [r["splash"] for r in rows if r["splash"]]
    if win:
        print(f"average: window {sum(win) / len(win):.2f}s" + (f" · splash {sum(spl) / len(spl):.2f}s" if spl else ""))


if __name__ == "__main__":
    main()
