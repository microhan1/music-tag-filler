"""Lyrics: tag round trip per format, backup / undo, the LRCLIB matching rules,
and LRCLIB's 503 handling (no network). The texts below are made up."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys

import pytest
from mutagen.flac import FLAC
from mutagen.oggvorbis import OggVorbis

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import net  # noqa: E402
import pipeline  # noqa: E402
import search_lyrics as sl  # noqa: E402
import tags  # noqa: E402
from tests.test_tags import FIXTURES, NAMES, _ensure_fixtures  # noqa: E402

TEXT = "첫 번째 줄입니다\nsecond made-up line\n三行目のテスト"


def _sha(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


@pytest.fixture(params=NAMES)
def sample(request, tmp_path):
    _ensure_fixtures()
    dst = tmp_path / request.param
    shutil.copy(os.path.join(FIXTURES, request.param), dst)
    tags.write_file(str(dst), tags.Tags(title="T", artist="A"))
    return str(dst)


# ------------------------------------------------------------------ tags
def test_lyrics_roundtrip_every_format(sample):
    assert tags.read_file(sample).lyrics == ""
    tags.write_file(sample, tags.Tags(title="T", artist="A"), lyrics=TEXT)
    assert tags.read_file(sample).lyrics == TEXT
    assert tags.read_lyrics(sample) == TEXT


def test_save_without_lyrics_keeps_them(sample):
    tags.write_file(sample, tags.Tags(title="T", artist="A"), lyrics=TEXT)
    tags.write_file(sample, tags.Tags(title="T2", artist="A"))
    assert tags.read_file(sample).lyrics == TEXT


def test_empty_string_removes_lyrics(sample):
    tags.write_file(sample, tags.Tags(title="T", artist="A"), lyrics=TEXT)
    tags.write_file(sample, tags.Tags(title="T", artist="A"), lyrics="")
    assert tags.read_file(sample).lyrics == ""


@pytest.mark.parametrize("name,cls", [("sample-b.flac", FLAC), ("sample-c.ogg", OggVorbis)])
def test_unsyncedlyrics_from_other_tools_counts(tmp_path, name, cls):
    _ensure_fixtures()
    path = str(tmp_path / name)
    shutil.copy(os.path.join(FIXTURES, name), path)
    f = cls(path)
    if f.tags is None:
        f.add_tags()
    f.tags["UNSYNCEDLYRICS"] = ["made up"]
    f.save()
    assert tags.read_file(path).lyrics == "made up"
    tags.write_file(path, tags.Tags(title="T"), lyrics=TEXT)
    f = cls(path)
    assert "unsyncedlyrics" not in f.tags  # one lyrics field, not two that disagree
    assert f.tags["lyrics"] == [TEXT]


def test_undo_after_adding_lyrics_is_byte_exact(sample):
    before = _sha(sample)
    tags.make_backup(sample)
    tags.write_file(sample, tags.Tags(title="T", artist="A"), lyrics=TEXT)
    assert tags.restore_backup(sample) is True
    assert _sha(sample) == before


def test_tag_level_undo_removes_added_lyrics(sample):
    backup = tags.make_backup(sample)
    with open(backup, encoding="utf-8") as f:
        record = json.load(f)
    assert record["lyrics"] == ""
    record["layout"] = None  # force the tag-value fallback
    with open(backup, "w", encoding="utf-8") as f:
        json.dump(record, f)
    tags.write_file(sample, tags.Tags(title="T", artist="A"), lyrics=TEXT)
    assert tags.restore_backup(sample) is False
    assert tags.read_file(sample).lyrics == ""


def test_old_backup_without_lyrics_key_leaves_lyrics(sample):
    backup = tags.make_backup(sample)
    with open(backup, encoding="utf-8") as f:
        record = json.load(f)
    del record["lyrics"]
    record["layout"] = None
    with open(backup, "w", encoding="utf-8") as f:
        json.dump(record, f)
    tags.write_file(sample, tags.Tags(title="T", artist="A"), lyrics=TEXT)
    tags.restore_backup(sample)
    assert tags.read_file(sample).lyrics == TEXT  # unknown original: not guessed


def test_save_file_passes_lyrics(sample):
    import prefs

    res = pipeline.save_file(sample, tags.Tags(title="T", artist="A"), None, prefs.Prefs(), lyrics=TEXT)
    assert tags.read_file(res.path).lyrics == TEXT
    assert os.path.exists(res.backup)


# ------------------------------------------------------------------ matching rules
def rec(track="Song", artist="Singer", duration=200.0, plain="made up words for a test song", synced=None,
        inst=False, rid=1):
    return {"id": rid, "trackName": track, "artistName": artist, "duration": duration,
            "plainLyrics": plain, "syncedLyrics": synced, "instrumental": inst}


def test_exact_record_is_found():
    status, r = sl.pick([rec()], "Song", "Singer", 201)
    assert status == sl.FOUND and r["id"] == 1


def test_other_artist_same_title_is_rejected():
    assert sl.pick([rec(artist="Somebody Else")], "Song", "Singer", 200)[0] == sl.NOT_FOUND


def test_artist_written_with_a_space_still_matches():
    assert sl.pick([rec(artist="岡田有希子")], "Song", "岡田 有希子", 200)[0] == sl.FOUND


def test_length_beyond_three_seconds_is_rejected():
    assert sl.pick([rec(duration=204.5)], "Song", "Singer", 200)[0] == sl.NOT_FOUND
    assert sl.pick([rec(duration=203.0)], "Song", "Singer", 200)[0] == sl.FOUND


@pytest.mark.parametrize("file_title,record_title", [
    ("Song", "Song (Instrumental)"),
    ("Song (Instrumental)", "Song"),
    ("Song -Off Vocal-", "Song"),
    ("Song (TV Size)", "Song"),
    ("Song", "Song (TV-Size)"),
    ("Song", "Song（instrumental）"),  # full-width brackets
])
def test_version_must_match(file_title, record_title):
    assert sl.pick([rec(track=record_title)], file_title, "Singer", 200)[0] == sl.NOT_FOUND


def test_same_version_matches():
    assert sl.pick([rec(track="Song (TV Size)")], "Song (TV-Size)", "Singer", 200)[0] == sl.FOUND


def test_timed_lyrics_running_past_the_end_are_rejected():
    full_song = rec(synced="[00:10.00]a\n[03:58.00]b", duration=106.0, rid=7)
    assert sl.pick([full_song], "Song", "Singer", 106)[0] == sl.NOT_FOUND
    fits = rec(synced="[00:10.00]a\n[01:44.00]b", duration=106.0, rid=8)
    status, r = sl.pick([full_song, fits], "Song", "Singer", 106)
    assert status == sl.FOUND and r["id"] == 8


def test_record_with_timestamps_is_preferred():
    plain_only = rec(rid=1)
    timed = rec(rid=2, synced="[00:01.00]made up words for a test song")
    assert sl.pick([plain_only, timed], "Song", "Singer", 200)[1]["id"] == 2


def test_records_marked_without_lyrics():
    # reported as "listed without lyrics", not "instrumental": such marks were seen on songs with lyrics
    assert sl.pick([rec(inst=True, plain=None)], "Song", "Singer", 200)[0] == sl.NO_LYRICS


def test_plain_from_synced_drops_timestamps():
    assert sl.plain_from_synced("[00:01.00]one\n[00:02.50][00:09.00]two\n") == "one\ntwo"


# ------------------------------------------------------------------ find() and the network
class FakeResp:
    def __init__(self, status=200, data=None, headers=None):
        self.status_code = status
        self._data = data
        self.headers = headers or {}

    def json(self):
        return self._data


def test_instrumental_file_is_not_looked_up(monkeypatch):
    monkeypatch.setattr(net, "request", lambda *a, **k: pytest.fail("no request expected"))
    assert sl.find("Song (Off Vocal)", "Singer", 200).status == sl.INSTRUMENTAL
    assert sl.find("Song", "", 200).status == sl.NEED_TAGS


def test_busy_server_is_reported_not_raised(monkeypatch):
    def boom(*a, **k):
        raise net.RateLimited(1)

    monkeypatch.setattr(net, "request", boom)
    assert sl.find("Song", "Singer", 200).status == sl.BUSY


def test_second_query_joins_the_artist_name(monkeypatch):
    seen = []

    def fake(method, url, params=None, **k):
        seen.append(params)
        if "q" in params:
            return FakeResp(data=[rec(artist="岡田有希子", plain="first made up line\nsecond one")])
        return FakeResp(data=[])

    monkeypatch.setattr(net, "request", fake)
    found = sl.find("Song", "岡田 有希子", 200)
    assert found.status == sl.FOUND and found.text == "first made up line\nsecond one"
    assert seen[1]["q"].startswith("岡田有希子 ")


def test_find_lyrics_never_raises(monkeypatch):
    def broken(*a, **k):
        raise ValueError("unexpected")

    monkeypatch.setattr(sl, "find", broken)
    monkeypatch.setattr(pipeline, "log_error", lambda *a: None)
    assert pipeline.find_lyrics(tags.Tags(title="T", artist="A"), 200).status == sl.BUSY


def _scripted_session(monkeypatch, statuses):
    calls = []

    class S:
        def request(self, method, url, **k):
            calls.append(url)
            code = statuses[min(len(calls) - 1, len(statuses) - 1)]
            return FakeResp(code, [] if code == 200 else None, {"Retry-After": "1"} if code == 503 else {})

    monkeypatch.setattr(net, "session", lambda: S())
    monkeypatch.setattr(net.throttle, "wait", lambda *a, **k: None)
    waits = []
    monkeypatch.setattr(net, "_sleep", lambda sec, cancel: waits.append(sec))
    return calls, waits


def test_lrclib_503_backs_off_without_slowing_the_host(monkeypatch):
    calls, waits = _scripted_session(monkeypatch, [503, 503, 200])
    before = net.throttle._intervals.get("lrclib.net")
    resp = net.request("GET", "https://lrclib.net/api/search", params={"q": "x"})
    assert resp.status_code == 200 and len(calls) == 3
    assert waits == [1.0, 2.0]  # Retry-After 1, then doubling
    assert net.throttle._intervals.get("lrclib.net") == before


def test_musicbrainz_503_still_slows_the_host(monkeypatch):
    calls, waits = _scripted_session(monkeypatch, [503, 200])
    host = "musicbrainz.org"
    before = net.throttle._intervals.get(host)
    monkeypatch.setitem(net.throttle._intervals, host, before)
    net.request("GET", "https://musicbrainz.org/ws/2/recording", params={})
    assert net.throttle._intervals[host] > before


# ------------------------------------------------------------------ records that disagree
REAL = "\n".join(f"made up real line number {i} about the morning train" for i in range(30))
FAKE = "\n".join(f"totally different joke text {i} with other words entirely" for i in range(30))


def test_copies_of_one_wrong_text_do_not_outvote_a_real_one():
    # one uploader sent the same text six times (one per length) next to one real record
    spam = [rec(rid=100 + i, plain=FAKE, synced="[00:01.00]x", duration=198 + i) for i in range(6)]
    status, r = sl.pick(spam + [rec(rid=1, plain=REAL)], "Song", "Singer", 200)
    assert status == sl.CONFLICT and r is None


def test_two_real_sources_beat_many_copies():
    spam = [rec(rid=100 + i, plain=FAKE, synced="[00:01.00]x", duration=198 + i) for i in range(6)]
    real_a = rec(rid=1, plain=REAL)
    real_b = rec(rid=2, plain=REAL.replace("morning", "evening"))  # another person's transcription
    status, r = sl.pick(spam + [real_a, real_b], "Song", "Singer", 200)
    assert status == sl.FOUND and r["id"] in (1, 2)


def test_agreeing_records_are_found():
    status, r = sl.pick([rec(rid=1, plain=REAL), rec(rid=2, plain=REAL + "\nla")], "Song", "Singer", 200)
    assert status == sl.FOUND


def test_both_searches_are_judged_together(monkeypatch):
    # the first search held only copies of a wrong text; the real record came from the second
    spam = [rec(rid=100 + i, plain=FAKE, duration=198 + i) for i in range(6)]

    def fake(method, url, params=None, **k):
        return FakeResp(data=[rec(rid=1, plain=REAL)] if "q" in params else spam)

    monkeypatch.setattr(net, "request", fake)
    assert sl.find("Song", "Singer", 200).status == sl.CONFLICT


def test_one_failed_search_means_try_later(monkeypatch):
    def fake(method, url, params=None, **k):
        if "q" in params:
            raise net.RateLimited(1)
        return FakeResp(data=[rec(rid=1, plain=REAL)])

    monkeypatch.setattr(net, "request", fake)
    assert sl.find("Song", "Singer", 200).status == sl.BUSY


def test_conflict_is_reported_by_find(monkeypatch):
    data = [rec(rid=1, plain=REAL), rec(rid=2, plain=FAKE)]
    monkeypatch.setattr(net, "request", lambda *a, **k: FakeResp(data=data))
    assert sl.find("Song", "Singer", 200).status == sl.CONFLICT
