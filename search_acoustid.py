"""Find a song by sound: fpcalc (Chromaprint) -> AcoustID -> MusicBrainz data.

Only the fingerprint (a string of numbers) and the duration are sent.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading

import net
from match import SOURCE_ACOUSTID, SOURCE_MB, Candidate
from search_mb import CAA_RELEASE

LOOKUP_URL = "https://api.acoustid.org/v2/lookup"
# Register a free application key at https://acoustid.org/new-application and
# put it here or in settings.json ("acoustid_key"). Empty = no built-in key.
DEFAULT_API_KEY = ""
FPCALC_NAME = "fpcalc.exe" if sys.platform == "win32" else "fpcalc"


class FpcalcMissing(Exception):
    pass


class NoApiKey(Exception):
    pass


def find_fpcalc(configured: str | None = None) -> str | None:
    """settings path -> next to exe -> third_party/ (source or bundle) -> PATH."""
    candidates: list[str] = []
    if configured:
        candidates.append(configured)
    import i18n

    for base in (i18n.app_dir(), i18n.resource_dir()):
        candidates.append(os.path.join(base, FPCALC_NAME))
        candidates.append(os.path.join(base, "third_party", FPCALC_NAME))
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return shutil.which("fpcalc")


def fingerprint(path: str, fpcalc: str | None = None) -> tuple[float, str]:
    """(duration seconds, fingerprint string). Raises FpcalcMissing."""
    exe = find_fpcalc(fpcalc)
    if not exe:
        raise FpcalcMissing()
    creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run([exe, "-json", "-length", "120", path], capture_output=True, timeout=120,
                              creationflags=creation)
    except (OSError, subprocess.SubprocessError) as exc:
        raise FpcalcMissing() from exc
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace").strip() or "fpcalc failed")
    try:
        data = json.loads(proc.stdout.decode("utf-8", "replace"))
    except ValueError as exc:
        raise RuntimeError("fpcalc output unreadable") from exc
    return float(data.get("duration") or 0.0), str(data.get("fingerprint") or "")


def lookup(fp: str, duration: float, api_key: str | None = None, *, on_wait=None,
           cancel: threading.Event | None = None) -> list[Candidate]:
    key = (api_key or DEFAULT_API_KEY).strip()
    if not key:
        raise NoApiKey()
    resp = net.request("POST", LOOKUP_URL, data={
        "client": key, "duration": str(int(round(duration))), "fingerprint": fp,
        "meta": "recordings releases tracks compress", "format": "json",
    }, on_wait=on_wait, cancel=cancel)
    try:
        data = resp.json()
    except ValueError as exc:
        raise net.NetworkError("bad json") from exc
    if data.get("status") != "ok":
        err = (data.get("error") or {}).get("message", "") if isinstance(data.get("error"), dict) else ""
        code = (data.get("error") or {}).get("code") if isinstance(data.get("error"), dict) else None
        if code in (4, 5) or "api key" in err.lower():
            raise NoApiKey()
        raise net.NetworkError(err or "acoustid error")
    out: list[Candidate] = []
    for result in data.get("results") or []:
        score = float(result.get("score") or 0.0)
        for rec in result.get("recordings") or []:
            out.append(_candidate(rec, score))
    out.sort(key=lambda c: -(c.acoustid_score or 0))
    return out


def _artists(items: list | None) -> str:
    parts: list[str] = []
    for a in items or []:
        if isinstance(a, dict):
            parts.append(str(a.get("name") or ""))
            parts.append(str(a.get("joinphrase") or ""))
    return "".join(parts).strip()


def _candidate(rec: dict, score: float) -> Candidate:
    release = None
    for rel in rec.get("releases") or []:
        if isinstance(rel, dict):
            release = rel
            break
    album = year = track = ""
    release_id = None
    album_artist = ""
    if release:
        album = str(release.get("title") or "")
        date = release.get("date") or {}
        if isinstance(date, dict) and date.get("year"):
            year = str(date["year"])
        release_id = str(release.get("id") or "") or None
        album_artist = _artists(release.get("artists"))
        for medium in release.get("mediums") or []:
            for t in medium.get("tracks") or []:
                if t.get("position"):
                    track = str(t["position"])
                    break
            if track:
                break
    dur = rec.get("duration")
    return Candidate(
        title=str(rec.get("title") or ""),
        artist=_artists(rec.get("artists")),
        album=album,
        album_artist=album_artist,
        year=year,
        track=track,
        length=float(dur) if isinstance(dur, (int, float)) and dur > 0 else None,
        sources=[SOURCE_ACOUSTID, SOURCE_MB],
        cover_url=CAA_RELEASE.format(id=release_id, size=500) if release_id else None,
        thumb_url=CAA_RELEASE.format(id=release_id, size=250) if release_id else None,
        mb_recording_id=str(rec.get("id") or "") or None,
        mb_release_id=release_id,
        acoustid_score=score,
    )
