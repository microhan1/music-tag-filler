"""iTunes Search API (no key). Strong for K-pop and cover art."""
from __future__ import annotations

import threading

import net
from match import SOURCE_ITUNES, Candidate

SEARCH_URL = "https://itunes.apple.com/search"
COUNTRIES = ("KR", "US", "JP", "CN", "TW", "HK", "GB", "DE", "FR")
COUNTRY_FOR_LANG = {"ko": "KR", "en": "US", "zh-CN": "CN", "ja": "JP"}
FALLBACK_COUNTRY = "US"


def artwork(url: str | None, size: int) -> str | None:
    """iTunes returns 100x100 URLs; the same path serves any size."""
    if not url:
        return None
    for token in ("100x100bb", "60x60bb", "30x30bb"):
        if token in url:
            return url.replace(token, f"{size}x{size}bb")
    return url


def search(term: str, country: str = "US", limit: int = 20, *, on_wait=None,
           cancel: threading.Event | None = None) -> list[Candidate]:
    term = (term or "").strip()
    if not term:
        return []
    # Some storefronts (KR among them) sell no music, so the search there is
    # always empty; the US store answers Korean queries with the same songs.
    countries = [country] + [c for c in (FALLBACK_COUNTRY,) if c != country]
    out: list[Candidate] = []
    for c in countries:
        if cancel is not None and cancel.is_set():
            break
        params = {"term": term, "country": c, "media": "music", "entity": "song", "limit": limit}
        data = net.get_json(SEARCH_URL, params, on_wait=on_wait, cancel=cancel)
        for item in data.get("results") or []:
            if not isinstance(item, dict) or item.get("wrapperType") not in (None, "track"):
                continue
            out.append(_candidate(item))
        if out:
            break
    return out


def _candidate(item: dict) -> Candidate:
    ms = item.get("trackTimeMillis")
    date = str(item.get("releaseDate") or "")
    track = item.get("trackNumber")
    return Candidate(
        title=str(item.get("trackName") or ""),
        artist=str(item.get("artistName") or ""),
        album=str(item.get("collectionName") or ""),
        album_artist=str(item.get("collectionArtistName") or item.get("artistName") or ""),
        year=date[:4] if len(date) >= 4 and date[:4].isdigit() else "",
        track=str(track) if isinstance(track, int) else "",
        genre=str(item.get("primaryGenreName") or ""),
        length=ms / 1000.0 if isinstance(ms, (int, float)) and ms > 0 else None,
        sources=[SOURCE_ITUNES],
        cover_url=artwork(item.get("artworkUrl100"), 1000),
        thumb_url=artwork(item.get("artworkUrl100"), 100),
        itunes_id=str(item.get("trackId") or "") or None,
    )
