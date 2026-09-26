"""iTunes Search API (no key). Strong for K-pop and cover art."""
from __future__ import annotations

import threading

import net
from match import SOURCE_ITUNES, Candidate

SEARCH_URL = "https://itunes.apple.com/search"
COUNTRIES = ("KR", "US", "JP", "CN", "TW", "HK", "GB", "DE", "FR")
COUNTRY_FOR_LANG = {"ko": "KR", "en": "US", "zh-CN": "CN", "ja": "JP"}
FALLBACK_COUNTRY = "US"
# Storefronts with no music catalogue: the search API always answers 0 results
# there, so asking them only costs a request slot. KR was confirmed by probing.
EMPTY_STOREFRONTS: set[str] = {"KR"}
_empty_hits: dict[str, int] = {}


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
    # The US store answers Korean and Japanese queries too, so it is the fallback
    # for a storefront that returns nothing; empty storefronts are skipped outright.
    countries = [c for c in (country, FALLBACK_COUNTRY) if c not in EMPTY_STOREFRONTS]
    if not countries:
        countries = [FALLBACK_COUNTRY]
    countries = list(dict.fromkeys(countries))
    out: list[Candidate] = []
    for i, c in enumerate(countries):
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
        if i == 0 and c != FALLBACK_COUNTRY:
            _note_empty(c)
    return out


def album_artwork(album: str, artist: str, country: str = "US", *, on_wait=None,
                  cancel: threading.Event | None = None) -> str | None:
    """Large artwork URL for an album found by name (+ artist), or None. Used when a
    MusicBrainz candidate has no Cover Art Archive image but the album is on iTunes."""
    from match import similarity

    album = (album or "").strip()
    if not album:
        return None
    countries = list(dict.fromkeys(c for c in (country, FALLBACK_COUNTRY) if c not in EMPTY_STOREFRONTS)) or [FALLBACK_COUNTRY]
    for c in countries:
        if cancel is not None and cancel.is_set():
            return None
        params = {"term": f"{artist} {album}".strip(), "country": c, "media": "music", "entity": "album", "limit": 10}
        data = net.get_json(SEARCH_URL, params, on_wait=on_wait, cancel=cancel)
        best, best_sim = None, 0.0
        for item in data.get("results") or []:
            if not isinstance(item, dict) or not item.get("artworkUrl100"):
                continue
            sim = similarity(str(item.get("collectionName") or ""), album)
            if artist and similarity(str(item.get("artistName") or ""), artist) < 0.3:
                sim *= 0.8
            if sim > best_sim:
                best, best_sim = item, sim
        if best is not None and best_sim >= 0.6:
            return artwork(best.get("artworkUrl100"), 1000)
        if data.get("results"):
            break  # the storefront answered; a different store will not change the match
    return None


def _note_empty(country: str) -> None:
    """Three empty answers in a row and the storefront is skipped for this session."""
    _empty_hits[country] = _empty_hits.get(country, 0) + 1
    if _empty_hits[country] >= 3:
        EMPTY_STOREFRONTS.add(country)


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
