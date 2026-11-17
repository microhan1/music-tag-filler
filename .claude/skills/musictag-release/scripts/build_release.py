"""Build music-tag-filler.exe for a release without touching the copy the user may be running.

    python .claude/skills/musictag-release/scripts/build_release.py

- Always builds to build\\release-dist: build.bat's PyInstaller line with --distpath, run from a
  temporary copy of build.bat that is deleted afterwards. dist\\ is never written here: the
  user runs the tool from there, and it only receives the uploaded release file. A running
  music-tag-filler is reported, never closed.
- dist\\settings.json is copied to build\\dist-settings.backup.json first; its contents are
  never printed.
- acoustid_key.txt and third_party\\fpcalc.exe must exist (the key is bundled from the file;
  its value is never printed).
Prints the path, size and SHA-256 of the exe it built.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
PYI_LINE = "python -m PyInstaller --noconfirm --clean --onefile --windowed ^"
ALT_DIST = os.path.join("build", "release-dist")


def running_paths() -> list[str]:
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "Get-Process music-tag-filler -ErrorAction SilentlyContinue | ForEach-Object { $_.Path }"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    os.chdir(REPO)
    for need in ("acoustid_key.txt", os.path.join("third_party", "fpcalc.exe"), "build.bat"):
        if not os.path.isfile(need):
            print(f"missing: {need} — stop (the exe would ship without it)")
            return 1
    os.makedirs("build", exist_ok=True)
    settings = os.path.join("dist", "settings.json")
    if os.path.isfile(settings):
        shutil.copy2(settings, os.path.join("build", "dist-settings.backup.json"))
        print("dist\\settings.json backed up to build\\dist-settings.backup.json (contents not shown)")

    running = running_paths()
    if running:
        print(f"music-tag-filler is running ({len(running)} process(es)): left alone, the build does not touch it")
    src = open("build.bat", encoding="utf-8", newline="").read()
    if src.count(PYI_LINE) != 1:
        print("build.bat's PyInstaller line changed: update PYI_LINE in this script")
        return 1
    exe = os.path.join(ALT_DIST, "music-tag-filler.exe")
    if os.path.exists(exe):
        os.remove(exe)  # never report an old build as the new one
    bat = "build_release_tmp.bat"
    with open(bat, "w", encoding="utf-8", newline="") as f:
        f.write(src.replace(PYI_LINE, PYI_LINE[:-2] + f" --distpath {ALT_DIST} ^"))
    try:
        proc = subprocess.run(["cmd", "/c", os.path.join(REPO, bat)], capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    finally:
        os.remove(bat)
    print("\n".join((proc.stdout + proc.stderr).splitlines()[-3:]))
    rc = proc.returncode
    if rc != 0 or not os.path.isfile(exe):
        print(f"build failed (exit {rc})")
        return 1
    print(f"built: {os.path.join(REPO, exe)}")
    print(f"size: {os.path.getsize(exe):,} bytes")
    print(f"sha256: {sha256(exe).upper()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
