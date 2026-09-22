"""Candidate model, file-name guessing, match scoring and merging.

Score 0..100 = text similarity (up to 70) + length agreement (up to 20)
+ source confidence (up to 10). Candidates that look like the same
recording from two sources are merged into one row listing both sources;
candidates that disagree stay as separate rows.
"""
from __future__ import annotations

import dataclasses
import difflib
import os
import re
import unicodedata

SOURCE_ITUNES = "iTunes"
SOURCE_MB = "MusicBrainz"
SOURCE_ACOUSTID = "AcoustID"

AUTO_SELECT_SCORE = 90
LENGTH_TOLERANCE = 5.0  # seconds; beyond this the length part is penalised

_SOURCE_WEIGHT = {SOURCE_ITUNES: 10, SOURCE_MB: 8, SOURCE_ACOUSTID: 10}


@dataclasses.dataclass
class Candidate:
    title: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    year: str = ""
    track: str = ""
    genre: str = ""
    length: float | None = None  # seconds
    sources: list[str] = dataclasses.field(default_factory=list)
    cover_url: str | None = None  # large image
    thumb_url: str | None = None  # small image for the table
    itunes_id: str | None = None
    mb_recording_id: str | None = None
    mb_release_id: str | None = None
    acoustid_score: float | None = None  # 0..1 from the fingerprint service
    score: int = 0

    def source_label(self) -> str:
        return "+".join(self.sources)

    def tag_values(self) -> dict[str, str]:
        return {
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "album_artist": self.album_artist or self.artist,
            "year": self.year,
            "track": self.track,
            "genre": self.genre,
        }


# ------------------------------------------------------------------ text
_STRIP_RE = re.compile(r"[\s\-_\.\,\!\?\'\"\(\)\[\]\{\}\:;/\\&+*~`^|<>=@#$%]+")
_FEAT_RE = re.compile(r"\s*[\(\[]?(feat\.?|ft\.?|featuring)\s+[^\)\]]*[\)\]]?", re.IGNORECASE)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").casefold()
    text = _FEAT_RE.sub("", text)
    return _STRIP_RE.sub("", text)


def similarity(a: str, b: str) -> float:
    """0..1, order-insensitive enough for 'Artist Title' vs 'Title Artist'."""
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ratio = difflib.SequenceMatcher(None, na, nb).ratio()
    if na in nb or nb in na:
        ratio = max(ratio, min(len(na), len(nb)) / max(len(na), len(nb)) * 0.5 + 0.5)
    return ratio


_TRACK_PREFIX_RE = re.compile(r"^\s*(?:\d{1,3}[\.\-_\s]+|\[\d+\]\s*|\(\d+\)\s*)")
_JUNK_RE = re.compile(r"\s*[\(\[](official|mv|m/v|audio|lyrics?|hd|hq|\d{3,4}p)[^\)\]]*[\)\]]", re.IGNORECASE)


def guess_from_filename(path: str) -> tuple[str, str]:
    """('artist', 'title') from 'Artist - Title.mp3'; ('', stem) when no dash."""
    stem = os.path.splitext(os.path.basename(path))[0]
    stem = _TRACK_PREFIX_RE.sub("", stem)
    stem = _JUNK_RE.sub("", stem).replace("_", " ").strip()
    for sep in (" - ", " \u2013 ", " \u2014 ", "-"):
        if sep in stem:
            left, right = stem.split(sep, 1)
            left, right = left.strip(), right.strip()
            if left and right:
                return left, right
    return "", stem


_GENERIC_RE = re.compile(r"^(track|audio|song|untitled|unknown|new|recording|rec)?[\s_\-#]*\d*$", re.IGNORECASE)


def is_generic_name(title: str, artist: str = "") -> bool:
    """'track01', 'Untitled 3', '07': a name that says nothing about the song.
    Such a query must never auto-select a candidate."""
    if artist.strip():
        return False
    # a one-character CJK title (many Japanese songs) is a real name; digits alone are not
    return bool(_GENERIC_RE.match(normalize(title)))


def build_query(title: str, artist: str) -> str:
    """'Artist - Title' so split_query() can take it apart again."""
    title, artist = (title or "").strip(), (artist or "").strip()
    if title and artist:
        return f"{artist} - {title}"
    return title or artist


def split_query(query: str) -> tuple[str, str]:
    """Best-effort ('artist', 'title') from a free-text query typed by the user."""
    query = query.strip()
    for sep in (" - ", " \u2013 ", " \u2014 "):
        if sep in query:
            a, b = query.split(sep, 1)
            return a.strip(), b.strip()
    return "", query


# ------------------------------------------------------------------ scoring
def score(cand: Candidate, query_title: str, query_artist: str, file_length: float | None) -> int:
    """0..100. Higher is better. Sets cand.score and returns it."""
    text = _text_similarity(cand, query_title, query_artist)
    length = _length_agreement(cand.length, file_length)
    source = max((_SOURCE_WEIGHT.get(s, 5) for s in cand.sources), default=5)
    if SOURCE_ACOUSTID in cand.sources and cand.acoustid_score is not None:
        # a fingerprint hit is strong evidence even when the query text is empty
        text = max(text, cand.acoustid_score)
    total = round(text * 70 + length + source)
    cand.score = max(0, min(100, total))
    return cand.score


def _text_similarity(cand: Candidate, query_title: str, query_artist: str) -> float:
    if not query_title and not query_artist:
        return 0.0
    if query_title and query_artist:
        return 0.6 * similarity(cand.title, query_title) + 0.4 * similarity(cand.artist, query_artist)
    query = query_title or query_artist
    combined = f"{cand.artist} {cand.title}"
    return max(similarity(cand.title, query), similarity(combined, query), 0.8 * similarity(cand.artist, query))


def _length_agreement(cand_len: float | None, file_len: float | None) -> float:
    if not cand_len or not file_len:
        return 10.0
    diff = abs(cand_len - file_len)
    if diff <= 2.0:
        return 20.0
    if diff <= LENGTH_TOLERANCE:
        return 20.0 - (diff - 2.0) * 2.0  # 20 -> 14
    return max(0.0, 14.0 - (diff - LENGTH_TOLERANCE) * 2.0)


# ------------------------------------------------------------------ merging
def _same_recording(a: Candidate, b: Candidate) -> bool:
    if normalize(a.title) != normalize(b.title) or normalize(a.artist) != normalize(b.artist):
        return False
    if a.length and b.length and abs(a.length - b.length) > 3.0:
        return False
    if a.album and b.album and normalize(a.album) != normalize(b.album):
        return False
    return True


def merge(cands: list[Candidate]) -> list[Candidate]:
    """Fold identical recordings from different sources into one row."""
    merged: list[Candidate] = []
    for cand in cands:
        for other in merged:
            if set(cand.sources) & set(other.sources):
                continue
            if _same_recording(cand, other):
                _fill(other, cand)
                break
        else:
            merged.append(dataclasses.replace(cand, sources=list(cand.sources)))
    return merged


def _fill(target: Candidate, extra: Candidate) -> None:
    for name in ("album", "album_artist", "year", "track", "genre", "cover_url", "thumb_url",
                 "itunes_id", "mb_recording_id", "mb_release_id", "length"):
        if not getattr(target, name) and getattr(extra, name):
            setattr(target, name, getattr(extra, name))
    if extra.acoustid_score is not None and (target.acoustid_score is None or extra.acoustid_score > target.acoustid_score):
        target.acoustid_score = extra.acoustid_score
    for s in extra.sources:
        if s not in target.sources:
            target.sources.append(s)


def rank(cands: list[Candidate], query_title: str, query_artist: str, file_length: float | None) -> list[Candidate]:
    merged = merge(cands)
    for c in merged:
        score(c, query_title, query_artist, file_length)
    merged.sort(key=lambda c: (-c.score, -len(c.sources), c.title))
    return merged
