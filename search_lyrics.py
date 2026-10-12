"""Lyrics from LRCLIB (https://lrclib.net), a free community lyrics database.

Only the title, the artist and the track length are sent. A record is used only
when everything agrees, because a wrong lyric is worse than none and is not
noticed until the song plays:

- the artist matches (a title alone found another singer's song of the same name);
- the title matches closely, and so does the version: an "(Instrumental)" /
  "Off Vocal" / "Karaoke" or a "TV size" title only pairs with the same kind of
  record (without this check 17 instrumental files in a test library matched
  vocal lyrics);
- the length is within LENGTH_TOLERANCE seconds;
- timed lyrics do not run past the end of the file (a "TV size" record with
  a correct 106 s length carried the full 238 s song);
- the records that pass agree with each other. Anyone can submit lyrics, and
  one song had the same made-up text submitted six times (consecutive IDs, one
  per length) next to two real ones, so a plain majority would have picked it.
  Near-identical copies count as one source; sources that tell the same text
  form a camp; the largest camp wins, and a tie means "do not add" (CONFLICT).

Files whose title says instrumental are not looked up at all. Only the plain
(unsynced) text is returned; timed lyrics are used for the check above.
Nothing the server sends is trusted to have the documented types.
"""
from __future__ import annotations

import dataclasses
import difflib
import re
import threading
import unicodedata

import match
import net

API_SEARCH = "https://lrclib.net/api/search"
LENGTH_TOLERANCE = 3.0  # seconds between the file and the record
END_TOLERANCE = 5.0  # last timestamp may run this far past the end (fade-outs)
TITLE_MIN = 0.9  # plain ratio of normalised titles; "Song" vs "Song 2" must not pass
ARTIST_MIN = 0.8
SAME_TEXT = 0.95  # one uploader's copies
AGREE_TEXT = 0.6  # two sources tell the same lyric
COMPARE_CHARS = 600
MIN_TEXT_CHARS = 10  # letters; "(Instrumental)" or "♪" alone is not a lyric
MAX_TEXT_CHARS = 30000  # a lyric this long is not a lyric
MAX_RECORDS = 60  # two searches return at most 20 each today
MAX_COMPARED = 30  # text comparison is quadratic: 60 distinct records took 4.5 s, 30 about 1 s
# Letters (no spaces or marks) per second of song. Checked only for a lone record without
# timestamps. Found lyrics of that kind ran 0.4-3.3 chars a second; fast English rap is
# about 16 letters; the wrong lyric that set this (a whole song under an 87 s intro) ran 16.
MAX_UNCHECKED_RATE = 12.0

FOUND = "found"
NOT_FOUND = "none"
INSTRUMENTAL = "instrumental"  # the file's title says instrumental / off vocal / karaoke
# the matching records are all marked "no lyrics". Not called instrumental on screen: three
# Every Little Thing songs with lyrics had 13-19 records each, every one marked that way.
NO_LYRICS = "no_lyrics"
BUSY = "busy"  # server overloaded or unreachable: try again later
CONFLICT = "conflict"  # matching records disagree about the text: nothing is added
NEED_TAGS = "need_tags"  # no title or artist to search with

_INST_RE = re.compile(
    r"\b(karaoke|off[\s\-]?vocal|instrumental|inst\.|backing track|minus one)"
    r"|[\(\[\-]\s*inst\s*[\)\]\-]|カラオケ|インスト|オフ\s*ボーカル|伴奏|纯音乐|純音楽|반주",
    re.IGNORECASE)
_SHORT_RE = re.compile(
    r"\btv[\s\-]?(size|ver\.?|version|edit)\b|\btvsize\b|\bshort[\s\-]?(ver\.?|version|size)\b"
    r"|tv\s*サイズ|テレビ\s*サイズ|ショート\s*(ver|バージョン)",
    re.IGNORECASE)
_TIMESTAMP_RE = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")
_LEADING_TAGS_RE = re.compile(r"^(\s*\[[^\]]*\])+")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_LETTERS_RE = re.compile(r"[\W_]+")


@dataclasses.dataclass
class LyricsResult:
    status: str
    text: str = ""  # plain lyrics when status == FOUND
    record_id: int | None = None


def _nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text if isinstance(text, str) else "")


def _str(value) -> str:
    return value if isinstance(value, str) else ""


def is_instrumental_title(title: str) -> bool:
    return bool(_INST_RE.search(_nfkc(title)))


def version_flags(title: str) -> tuple[bool, bool]:
    """(instrumental, short/TV version) as the title states them."""
    t = _nfkc(title)
    return bool(_INST_RE.search(t)), bool(_SHORT_RE.search(t))


def last_timestamp(lrc: str) -> float | None:
    values = [int(m) * 60 + float(s) for m, s in _TIMESTAMP_RE.findall(_str(lrc))]
    return max(values) if values else None


def plain_from_synced(lrc: str) -> str:
    lines = [_LEADING_TAGS_RE.sub("", line).strip() for line in _str(lrc).splitlines()]
    return "\n".join(lines).strip()


def clean_text(text: str) -> str:
    """Lyrics as they will be written: \\n line ends, no control characters, and
    no lone surrogates (they cannot be encoded and would make the save fail)."""
    text = _str(text).replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_RE.sub("", text)
    text = text.encode("utf-8", "replace").decode("utf-8")
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()


def record_text(record: dict) -> str:
    """The plain lyrics a record would give the file, "" when it has none worth writing."""
    text = clean_text(_str(record.get("plainLyrics"))) or clean_text(plain_from_synced(_str(record.get("syncedLyrics"))))
    # "(Instrumental)" or "[Karaoke]" as the whole text is a note, not a lyric
    letters = _LETTERS_RE.sub("", _INST_RE.sub("", _nfkc(text)))
    if len(letters) < MIN_TEXT_CHARS or len(text) > MAX_TEXT_CHARS:
        return ""
    return text


# A Hepburn syllable (ka, shi, tsu, kyo, n, the first of a doubled consonant). Romanised
# Japanese words split into these with nothing left over; English words mostly do not.
# Measured on LRCLIB texts: romanised lyrics 0.63-1.00 of their words, English 0.25-0.37.
_ROMAJI_WORD_RE = re.compile(
    r"^(?:(?:ky|gy|sh|ch|ts|ny|hy|by|py|my|ry|j|[kgsztdnhbpmyrwf])?[aeiou]|n(?![aeiouy])"
    r"|[kstpgdbcmfhjrz](?=[kstpgdbcmfhjrz]))+$")
ROMAJI_SHARE = 0.55
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7a3]")


def is_romanised(text: str) -> bool:
    """A Latin-only transliteration of a Japanese lyric (\"kimi no koto wo ...\")."""
    text = _nfkc(text)
    if _CJK_RE.search(text):
        return False
    words = [w for w in re.findall(r"[a-z]+", text.lower()) if len(w) >= 2]
    if len(words) < 20:
        return False
    return sum(bool(_ROMAJI_WORD_RE.match(w)) for w in words) / len(words) >= ROMAJI_SHARE


def _prefer_original_script(records: list[dict]) -> list[dict]:
    """When a song has records in its own script, romanised copies of it are dropped before
    the agreement check: they tell the same lyric but share no letters with it, so five
    ATARASHII GAKKO! songs came out as CONFLICT. With romanised records only, they stay."""
    if not any(_CJK_RE.search(record_text(r)) for r in records):
        return records
    kept = [r for r in records if not is_romanised(record_text(r))]
    return kept or records


def letters_per_second(record: dict, length: float) -> float:
    letters = _LETTERS_RE.sub("", _nfkc(record_text(record)))
    return len(letters) / length if length else 0.0


_MARKER_RE = re.compile(r"^\s*(\[[^\[\]\n]{1,40}\]\s*)+$")


def marker_only(text: str) -> str:
    """The text when a lyrics tag holds no lyrics, only a note: a player's marker such as
    "[COWON S9]" or "[3 LINES]" (12 of 471 files in one Korean library), or a few letters.
    "" when the tag is empty or holds real lyrics. Such a tag counts as empty: lyrics
    found on save replace it (the user's decision, 2026-10-12), and undo brings it back."""
    text = _str(text).strip()
    if not text:
        return ""
    letters = _LETTERS_RE.sub("", _INST_RE.sub("", _nfkc(text)))
    if _MARKER_RE.match(text) or len(letters) < MIN_TEXT_CHARS:
        return text[:40]
    return ""


def _norm_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() if a and b else 0.0


def _artist_ok(record_artist: str, artist: str) -> bool:
    a, b = match.normalize(record_artist), match.normalize(artist)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    # "Singer" inside "Singer & Friend": a duet credited to one of them. Not "ai" inside "aimer".
    if len(short) >= 3 and len(short) / len(long_) >= 0.34 and short in long_:
        return True
    return _norm_ratio(a, b) >= ARTIST_MIN


def _title_ok(record_title: str, title: str) -> bool:
    a, b = match.normalize(record_title), match.normalize(title)
    return bool(a) and (a == b or _norm_ratio(a, b) >= TITLE_MIN) and version_flags(record_title) == version_flags(title)


def _duration(record: dict) -> float | None:
    value = record.get("duration")
    if isinstance(value, bool):
        return None
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return None
    return duration if duration > 0 else None


def _length_ok(record: dict, length: float) -> bool:
    duration = _duration(record)
    return bool(length) and duration is not None and abs(duration - length) <= LENGTH_TOLERANCE


def _end_ok(record: dict, length: float) -> bool:
    end = last_timestamp(_str(record.get("syncedLyrics")))
    return end is None or end <= length + END_TOLERANCE


def _text_key(record: dict) -> str:
    text = _TIMESTAMP_RE.sub("", record_text(record))
    return _LETTERS_RE.sub("", _nfkc(text).casefold())[:COMPARE_CHARS]


def _agrees(a: str, b: str, threshold: float) -> bool:
    if not a or not b:
        return False
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    # the cheap upper bounds rule most pairs out before the full comparison
    return sm.real_quick_ratio() >= threshold and sm.quick_ratio() >= threshold and sm.ratio() >= threshold


def agreeing_camp(records: list[dict]) -> list[dict] | None:
    """The records of the largest group of sources that tell the same text,
    or None when two groups of the same size disagree."""
    if len(records) <= 1:
        return records
    keys = [_text_key(r) for r in records]
    sources: list[list[int]] = []  # near-identical copies are one source
    for i, key in enumerate(keys):
        for src in sources:
            if _agrees(key, keys[src[0]], SAME_TEXT):
                src.append(i)
                break
        else:
            sources.append([i])
    camp_of = list(range(len(sources)))  # union-find over sources that agree

    def root(i: int) -> int:
        while camp_of[i] != i:
            camp_of[i] = camp_of[camp_of[i]]
            i = camp_of[i]
        return i

    for a in range(len(sources)):
        for b in range(a + 1, len(sources)):
            if root(a) != root(b) and _agrees(keys[sources[a][0]], keys[sources[b][0]], AGREE_TEXT):
                camp_of[root(b)] = root(a)
    camps: dict[int, list[int]] = {}
    for i in range(len(sources)):
        camps.setdefault(root(i), []).append(i)
    sizes = sorted((len(members) for members in camps.values()), reverse=True)
    if len(sizes) > 1 and sizes[0] == sizes[1]:
        return None
    best = max(camps.values(), key=len)
    return [records[i] for src in best for i in sources[src]]


def pick(records: list, title: str, artist: str, length: float) -> tuple[str, dict | None]:
    """(status, record) for the search results under the rules above."""
    same_song = [r for r in records[:MAX_RECORDS] if isinstance(r, dict)
                 and _title_ok(_str(r.get("trackName")), title)
                 and _artist_ok(_str(r.get("artistName")), artist)
                 and _length_ok(r, length)]
    if not same_song:
        return NOT_FOUND, None
    with_text = [r for r in same_song if not r.get("instrumental") and record_text(r) and _end_ok(r, length)]
    if not with_text:
        if any(r.get("instrumental") is True for r in same_song):
            return NO_LYRICS, None
        return NOT_FOUND, None
    with_text = _prefer_original_script(with_text)
    with_text.sort(key=lambda r: abs((_duration(r) or 0) - length))
    camp = agreeing_camp(with_text[:MAX_COMPARED])
    if camp is None:
        return CONFLICT, None
    # a record with timed lyrics passed the end-of-song check, so it is the safer pick
    camp.sort(key=lambda r: (not _str(r.get("syncedLyrics")).strip(), abs((_duration(r) or 0) - length)))
    chosen = camp[0]
    if len(camp) == 1 and not _str(chosen.get("syncedLyrics")).strip() and letters_per_second(chosen, length) > MAX_UNCHECKED_RATE:
        # one record, no timestamps, nothing to compare with, and far more text than the
        # song has time for: another song's lyrics under this name (an 87 s intro carried
        # another song's whole lyrics, 16 letters a second)
        return NOT_FOUND, None
    return FOUND, chosen


def _search(params: dict, cancel: threading.Event | None) -> list:
    resp = net.request("GET", API_SEARCH, params=params, cancel=cancel)
    if resp.status_code == 404:
        return []
    if resp.status_code >= 400:
        raise net.NetworkError(f"HTTP {resp.status_code}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise net.NetworkError("bad json") from exc
    return data if isinstance(data, list) else []


def find(title: str, artist: str, length: float, *, cancel: threading.Event | None = None) -> LyricsResult:
    """Look one track up. Never raises for network trouble: that is BUSY."""
    title, artist = _str(title).strip(), _str(artist).strip()
    if not title or not artist:
        return LyricsResult(NEED_TAGS)
    if is_instrumental_title(title):
        return LyricsResult(INSTRUMENTAL)
    try:
        length = float(length or 0)
    except (TypeError, ValueError):
        length = 0.0
    if length <= 0:
        return LyricsResult(NOT_FOUND)  # no length, no way to tell the versions apart
    queries = [
        {"track_name": title, "artist_name": artist},
        # "岡田 有希子" vs "岡田有希子": the keyword search treats the space as two words
        {"q": f"{artist.replace(' ', '')} {match.base_title(title)}"},
    ]
    # Both searches are always asked and judged together: in one song the first search
    # returned only six copies of a made-up text and the real records came from the
    # second. For the same reason a failed search means "try later", not "use what came".
    records: list = []
    seen: set = set()
    for params in queries:
        if cancel is not None and cancel.is_set():
            return LyricsResult(BUSY)
        try:
            found = _search(params, cancel)
        except (net.NetworkError, net.RateLimited):
            return LyricsResult(BUSY)
        for r in found:
            if not isinstance(r, dict):
                continue
            key = r.get("id")
            if isinstance(key, (int, str)) and not isinstance(key, bool):
                if key in seen:
                    continue
                seen.add(key)
            records.append(r)
    status, record = pick(records, title, artist, length)
    if status == FOUND and record is not None:
        rid = record.get("id")
        return LyricsResult(FOUND, record_text(record), rid if isinstance(rid, int) and not isinstance(rid, bool) else None)
    return LyricsResult(status)
