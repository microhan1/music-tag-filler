"""The steps shared by the GUI and the CLI: search, fingerprint, cover, save.

Everything network-related reports 429 waits through `on_wait(seconds)` and
can be cancelled through a threading.Event. Search functions never raise
for a single source failing; they return what they got plus an error list.
"""
from __future__ import annotations

import concurrent.futures
import dataclasses
import os
import threading
from typing import Callable

import match
import net
import search_acoustid
import search_itunes
import search_mb
import tags
from match import Candidate
from prefs import Prefs

WaitCallback = Callable[[float], None]

ERR_NETWORK = "err_network"
ERR_RATE_LIMIT = "err_rate_limit_failed"
ERR_FPCALC = "err_fpcalc_missing"
ERR_ACOUSTID_KEY = "err_acoustid_key"
ERR_FINGERPRINT = "err_fingerprint_failed"


@dataclasses.dataclass
class SearchResult:
    candidates: list[Candidate]
    errors: list[str]  # language keys
    query_title: str = ""
    query_artist: str = ""
    weak_query: bool = False  # generic file name: never auto-select


@dataclasses.dataclass
class SaveResult:
    path: str  # final path (after an optional rename)
    backup: str
    cover_failed: bool = False
    renamed: bool = False


LOG_NAME = "music-tag-filler.log"


def log_error(where: str, exc: BaseException) -> None:
    """Append one line to the log beside the exe; the GUI only shows a short message."""
    import time

    import i18n

    try:
        with open(os.path.join(i18n.app_dir(), LOG_NAME), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {where}: {exc!r}\n")
    except OSError:
        pass


def initial_query(info: tags.FileInfo) -> tuple[str, str]:
    """('title', 'artist') from the tags, else guessed from the file name."""
    if info.tags.title:
        return info.tags.title, info.tags.artist
    artist, title = match.guess_from_filename(info.path)
    return title, artist


def auto_pick(result: SearchResult) -> Candidate | None:
    """The first candidate when it clears the auto-select bar and the query was meaningful."""
    if result.weak_query or not result.candidates:
        return None
    best = result.candidates[0]
    return best if best.score >= match.AUTO_SELECT_SCORE else None


def apply_candidate(current: tags.Tags, cand: Candidate, overwrite: bool) -> tags.Tags:
    """Tags after applying a candidate. overwrite=False only fills empty fields,
    which is what automatic picks do: a best-album rip must keep its album."""
    merged = current.as_dict()
    for key, value in cand.tag_values().items():
        if value and (overwrite or not merged.get(key)):
            merged[key] = value
    return tags.Tags.from_dict(merged)


def query_text(info: tags.FileInfo) -> str:
    title, artist = initial_query(info)
    return match.build_query(title, artist)


def search_text(query: str, country: str, file_length: float | None, *, on_wait: WaitCallback | None = None,
                cancel: threading.Event | None = None) -> SearchResult:
    """iTunes + MusicBrainz for one query string, merged and ranked."""
    artist, title = match.split_query(query)
    cands: list[Candidate] = []
    errors: list[str] = []

    def guarded(fn) -> tuple[list[Candidate], str | None]:
        if cancel is not None and cancel.is_set():
            return [], None
        try:
            return fn(), None
        except net.RateLimited:
            return [], ERR_RATE_LIMIT
        except net.NetworkError:
            return [], ERR_NETWORK

    # the two sources have separate rate limits, so ask them at the same time
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(guarded, lambda: search_itunes.search(query, country, on_wait=on_wait, cancel=cancel)),
            pool.submit(guarded, lambda: search_mb.search(match.base_title(title), artist, query, on_wait=on_wait, cancel=cancel)),
        ]
        for fut in futures:
            found, err = fut.result()
            cands.extend(found)
            if err:
                errors.append(err)
    if not title and not artist:
        title = query
    ranked = match.rank(cands, title, artist, file_length)
    return SearchResult(ranked, errors, title, artist, match.is_generic_name(title, artist))


def search_sound(path: str, prefs: Prefs, query: str = "", file_length: float | None = None, *,
                 on_wait: WaitCallback | None = None, cancel: threading.Event | None = None) -> SearchResult:
    """fpcalc -> AcoustID -> candidates (with MusicBrainz release data)."""
    artist, title = match.split_query(query)
    try:
        duration, fp = search_acoustid.fingerprint(path, prefs.fpcalc_path or None)
    except search_acoustid.FpcalcMissing as exc:
        log_error("fpcalc missing", exc)
        return SearchResult([], [ERR_FPCALC], title, artist)
    except Exception as exc:
        log_error("fingerprint", exc)
        return SearchResult([], [ERR_FINGERPRINT], title, artist)
    if not fp:
        return SearchResult([], [ERR_FINGERPRINT], title, artist)
    try:
        cands = search_acoustid.lookup(fp, duration, prefs.acoustid_key, on_wait=on_wait, cancel=cancel)
    except search_acoustid.NoApiKey as exc:
        log_error("acoustid key", exc)
        return SearchResult([], [ERR_ACOUSTID_KEY], title, artist)
    except net.RateLimited as exc:
        log_error("acoustid rate limit", exc)
        return SearchResult([], [ERR_RATE_LIMIT], title, artist)
    except net.NetworkError as exc:
        log_error("acoustid network", exc)
        return SearchResult([], [ERR_NETWORK], title, artist)
    # AcoustID lists releases in no useful order and includes translated
    # pseudo-releases, so its album name can come out as an English rendering of
    # a Japanese title. Re-read the top hits from MusicBrainz, which picks the
    # earliest official release, so sound and text searches name albums alike.
    for cand in cands[:3]:
        if not cand.mb_recording_id:
            continue
        if cancel is not None and cancel.is_set():
            break
        try:
            full = search_mb.lookup(cand.mb_recording_id, on_wait=on_wait, cancel=cancel)
        except (net.NetworkError, net.RateLimited):
            continue
        if full is None:
            continue
        for name in ("title", "artist", "album", "album_artist", "year", "track", "genre",
                     "cover_url", "thumb_url", "mb_release_id", "length"):
            value = getattr(full, name)
            if value:
                setattr(cand, name, value)
    ranked = match.rank(cands, title, artist, file_length or duration)
    return SearchResult(ranked, [], title, artist)


def fetch_cover(cand: Candidate, country: str = "US", *, on_wait: WaitCallback | None = None,
                cancel: threading.Event | None = None) -> bytes | None:
    """Full-size cover for a candidate, or None. Tries the candidate's own image,
    then the Cover Art Archive release group, then the album on iTunes: many
    MusicBrainz releases carry no art although the album is on iTunes."""
    urls = [cand.cover_url]
    if cand.mb_release_group_id:
        urls.append(search_mb.CAA_RELEASE_GROUP.format(id=cand.mb_release_group_id, size=500))
    for url in urls:
        if not url or (cancel is not None and cancel.is_set()):
            continue
        try:
            data = net.get_bytes(url, on_wait=on_wait, cancel=cancel)
        except (net.NetworkError, net.RateLimited):
            data = None
        if data:
            return data
    if cand.album and (cancel is None or not cancel.is_set()):
        try:
            url = search_itunes.album_artwork(cand.album, cand.album_artist or cand.artist, country,
                                              on_wait=on_wait, cancel=cancel)
            if url:
                return net.get_bytes(url, on_wait=on_wait, cancel=cancel) or None
        except (net.NetworkError, net.RateLimited):
            return None
    return None


def fetch_thumb(cand: Candidate, *, cancel: threading.Event | None = None) -> bytes | None:
    if not cand.thumb_url:
        return None
    try:
        return net.get_bytes(cand.thumb_url, max_bytes=2 * 1024 * 1024, cancel=cancel) or None
    except (net.NetworkError, net.RateLimited):
        return None


def save_file(path: str, new_tags: tags.Tags, cover: bytes | None, prefs: Prefs, *, rename: bool | None = None) -> SaveResult:
    """Backup, write tags (+ cover if given), optionally rename. Raises tags.FileLocked."""
    if not os.access(path, os.W_OK):
        raise tags.FileLocked(path)
    backup = tags.make_backup(path)
    cover_failed = False
    prepared = None
    mime = "image/jpeg"
    if cover:
        try:
            prepared, mime = tags.prepare_cover(cover, prefs.cover_max_px)
        except Exception:
            cover_failed = True
    tags.write_file(path, new_tags, prepared, mime)
    result = SaveResult(path, backup, cover_failed)
    do_rename = prefs.rename if rename is None else rename
    if do_rename:
        target = tags.rename_target(path, new_tags)
        if target:
            result.path = tags.rename_file(path, target)
            result.backup = tags.backup_path(result.path)
            result.renamed = True
    return result
