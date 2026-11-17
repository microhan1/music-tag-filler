"""Check a built music-tag-filler.exe before it is uploaded.

    python .claude/skills/musictag-release/scripts/check_exe.py <new exe> [<previous release exe>]

1. bundled files: the AcoustID key file, fpcalc, icons, lang files, certifi, PIL fonts, splash
2. file list against the previous release exe (LESSONS D12: a smaller exe once lost certifi)
3. APP_VERSION inside the bundled net module equals net.py's
4. a copy in a temp folder is started with a dead proxy and its own TEMP (no request leaves,
   no user settings touched), the window titled 「음악 정보 채우기」 is found and closed with
   WM_CLOSE: exit code 0, no _MEI folder left
The key's value is never printed. Exit code 0 only when every check passes.
"""
from __future__ import annotations

import marshal
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8")
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tests"))
import measure_startup as ms  # noqa: E402  (offline_env, family, windows_of)

from PyInstaller.archive.readers import CArchiveReader  # noqa: E402

TITLE = "음악 정보 채우기"
REQUIRED = ("acoustid_key.txt", "third_party\\fpcalc.exe", "assets\\icon.ico", "assets\\icon.png",
            "lang\\ko.json", "lang\\en.json", "lang\\ja.json", "lang\\zh-CN.json", "certifi\\cacert.pem",
            "Splash-00.res")
WM_CLOSE = 0x0010


def names(exe: str) -> set[str]:
    return set(CArchiveReader(exe).toc)


def bundled_version(exe: str) -> str | None:
    pyz = CArchiveReader(exe).open_embedded_archive("PYZ.pyz")
    code = pyz.extract("net")
    if isinstance(code, tuple):
        code = code[1]
    if isinstance(code, bytes):
        code = marshal.loads(code)
    found = [c for c in code.co_consts if isinstance(c, str) and re.fullmatch(r"\d+\.\d+\.\d+", c)]
    return found[0] if found else None


def source_version() -> str:
    text = open(os.path.join(REPO, "net.py"), encoding="utf-8").read()
    return re.search(r'APP_VERSION = "([^"]+)"', text).group(1)


def launch(exe: str) -> tuple[bool, str]:
    root = tempfile.mkdtemp(prefix="mtf_release_check_")
    try:
        copy = os.path.join(root, "app", "music-tag-filler.exe")
        tmp = os.path.join(root, "tmp")
        os.makedirs(os.path.dirname(copy))
        os.makedirs(tmp)
        shutil.copy2(exe, copy)
        proc = subprocess.Popen([copy], cwd=os.path.dirname(copy), env=ms.offline_env(dict(os.environ, TEMP=tmp, TMP=tmp)))
        try:
            t0 = time.monotonic()
            wins = []
            while time.monotonic() - t0 < 90 and not wins:
                time.sleep(0.25)
                wins = [w for w in ms.windows_of(ms.family(proc.pid)) if w["caption"] and w["title"] == TITLE]
            if not wins:
                return False, "no window titled 「%s」 within 90 s" % TITLE
            up = time.monotonic() - t0
            time.sleep(2)
            ms.user32.PostMessageW(wins[0]["hwnd"], WM_CLOSE, 0, 0)
            rc = proc.wait(timeout=30)
            time.sleep(0.5)
            left = [d for d in os.listdir(tmp) if d.startswith("_MEI")]
            ok = rc == 0 and not left
            return ok, f"window 「{TITLE}」 after {up:.1f} s · exit code {rc} · _MEI left {len(left)}"
        finally:
            if proc.poll() is None:  # only the copy this script started
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    finally:
        time.sleep(1)
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    exe = os.path.abspath(sys.argv[1])
    prev = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else None
    bad = 0

    have = names(exe)
    missing = [n for n in REQUIRED if n not in have]
    bad += bool(missing)
    print(("✅" if not missing else "❌") + f" bundled files: {len(have)}" + (f", missing {missing}" if missing else ", required ones present"))

    if prev:
        before = names(prev)
        gone, new = sorted(before - have), sorted(have - before)
        bad += bool(gone)
        mark = "✅" if not gone and not new else ("❌" if gone else "⚠")
        print(f"{mark} against the previous exe: {len(gone)} gone {gone[:8]}, {len(new)} new {new[:8]}")
    else:
        print("⚠ no previous exe given: file list not compared")

    got, want = bundled_version(exe), source_version()
    bad += got != want
    print(("✅" if got == want else "❌") + f" bundled APP_VERSION {got} (net.py {want})")

    ok, what = launch(exe)
    bad += not ok
    print(("✅" if ok else "❌") + " offline start: " + what)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
