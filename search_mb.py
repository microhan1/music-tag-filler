"""MusicBrainz recording search and Cover Art Archive URLs (no key).

MusicBrainz asks for one request per second and a descriptive User-Agent;
both are handled in net.py.
"""
from __future__ import annotations

import re
import threading

import net
from match import SOURCE_MB, Candidate

SEARCH_URL = "https://musicbrainz.org/ws/2/recording"
LOOKUP_URL = "https://musicbrainz.org/ws/2/recording/{id}"
CAA_RELEASE = "https://coverartarchive.org/release/{id}/front-{size}"
CAA_RELEASE_GROUP = "https://coverartarchive.org/release-group/{id}/front-{size}"

_LUCENE_SPECIAL = re.compile(r'([+\-!(){}\[\]^"~*?:\\/]|&&|\|\|)')


def _quote(text: str) -> str:
    return '"' + _LUCENE_SPECIAL.sub(r"\\\1", text.strip()) + '"'


def build_query(title: str, artist: str, free_text: str = "") -> str:
    if title and artist:
        return f"recording:{_quote(title)} AND artist:{_quote(artist)}"
    if title:
        return f"recording:{_quote(title)}"
    return _LUCENE_SPECIAL.sub(r"\\\1", (free_text or artist).strip())


def search(title: str, artist: str, free_text: str = "", limit: int = 20, *, on_wait=None,
           cancel: threading.Event | None = None) -> list[Candidate]:
    queries = [build_query(title, artist, free_text)]
    # The fielded query misses artists known under another name (a Korean
    # alias of a Latin-script artist, say); plain text also searches aliases.
    plain = _LUCENE_SPECIAL.sub(r"\\\1", (free_text or f"{artist} {title}").strip())
    if plain and plain not in queries:
        queries.append(plain)
    out: list[Candidate] = []
    for query in queries:
        if not query or (cancel is not None and cancel.is_set()):
            continue
        data = net.get_json(SEARCH_URL, {"query": query, "fmt": "json", "limit": limit}, on_wait=on_wait, cancel=cancel)
        for rec in data.get("recordings") or []:
            if isinstance(rec, dict):
                out.append(candidate_from_recording(rec))
        if out:
            break
    return out


def lookup(recording_id: str, *, on_wait=None, cancel: threading.Event | None = None) -> Candidate | None:
    """Full recording by MBID, used after an AcoustID hit that lacks release data."""
    data = net.get_json(LOOKUP_URL.format(id=recording_id),
                        {"fmt": "json", "inc": "artist-credits+releases+release-groups+media+genres"}, on_wait=on_wait, cancel=cancel)
    return candidate_from_recording(data) if data.get("id") else None


# ------------------------------------------------------------------ parsing
def artist_credit(credits: list | None) -> str:
    parts: list[str] = []
    for c in credits or []:
        if isinstance(c, dict):
            parts.append(str(c.get("name") or (c.get("artist") or {}).get("name") or ""))
            parts.append(str(c.get("joinphrase") or ""))
    return "".join(parts).strip()


def _pick_release(releases: list) -> dict | None:
    """Earliest official release (compilations last) so the album is the one the song came out on."""
    best = None
    best_key = None
    for rel in releases:
        if not isinstance(rel, dict):
            continue
        status = str(rel.get("status") or "")
        rg = rel.get("release-group") or {}
        ptype = str(rg.get("primary-type") or "")
        secondary = rg.get("secondary-types") or []
        date = str(rel.get("date") or "9999")
        key = (
            0 if status == "Official" else 1,
            1 if secondary else 0,  # compilations, live albums, soundtracks last
            0 if ptype in ("Album", "EP") else 1 if ptype == "Single" else 2,
            date,
        )
        if best_key is None or key < best_key:
            best, best_key = rel, key
    return best


def _track_number(release: dict) -> str:
    for medium in release.get("media") or []:
        for track in (medium.get("track") or medium.get("tracks") or []):
            number = track.get("number") or track.get("position")
            if number:
                return str(number)
    return ""


def candidate_from_recording(rec: dict) -> Candidate:
    ms = rec.get("length")
    release = _pick_release(rec.get("releases") or [])
    year = ""
    album = ""
    album_artist = ""
    release_id = None
    release_group_id = None
    track = ""
    if release:
        album = str(release.get("title") or "")
        date = str(release.get("date") or "")
        year = date[:4] if len(date) >= 4 and date[:4].isdigit() else ""
        album_artist = artist_credit(release.get("artist-credit"))
        release_id = str(release.get("id") or "") or None
        release_group_id = str((release.get("release-group") or {}).get("id") or "") or None
        track = _track_number(release)
    if not year:
        first = str(rec.get("first-release-date") or "")
        year = first[:4] if len(first) >= 4 and first[:4].isdigit() else ""
    genres = [g.get("name") for g in rec.get("genres") or [] if isinstance(g, dict) and g.get("name")]
    return Candidate(
        title=str(rec.get("title") or ""),
        artist=artist_credit(rec.get("artist-credit")),
        album=album,
        album_artist=album_artist,
        year=year,
        track=track,
        genre=str(genres[0]) if genres else "",
        length=ms / 1000.0 if isinstance(ms, (int, float)) and ms > 0 else None,
        sources=[SOURCE_MB],
        cover_url=CAA_RELEASE.format(id=release_id, size=500) if release_id else None,
        thumb_url=CAA_RELEASE.format(id=release_id, size=250) if release_id else None,
        mb_recording_id=str(rec.get("id") or "") or None,
        mb_release_id=release_id,
        mb_release_group_id=release_group_id,
    )
