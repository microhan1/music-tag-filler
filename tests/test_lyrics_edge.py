"""Edge cases for lyrics: odd server answers, unusable texts, loose name matches,
non-Latin version words, and writing cleaned text to every format (no network)."""
from __future__ import annotations

import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import net  # noqa: E402
import search_lyrics as sl  # noqa: E402
import tags  # noqa: E402
from tests.test_lyrics import FakeResp, rec  # noqa: E402
from tests.test_tags import FIXTURES, NAMES, _ensure_fixtures  # noqa: E402

LYRIC = "made up words for a test song\nand a second made up line"


# ------------------------------------------------------------------ what counts as a lyric
def test_timestamps_only_is_not_a_lyric():
    r = rec(plain=None, synced="[00:01.00]\n[00:05.00]\n[00:09.00]")
    assert sl.record_text(r) == ""
    assert sl.pick([r], "Song", "Singer", 200)[0] == sl.NOT_FOUND  # never "found" with an empty text


@pytest.mark.parametrize("text", ["(Instrumental)", "♪", "...", "  \n  "])
def test_placeholders_are_not_lyrics(text):
    assert sl.record_text(rec(plain=text)) == ""


def test_absurdly_long_text_is_rejected():
    assert sl.record_text(rec(plain="la " * 20000)) == ""


def test_text_is_cleaned_for_writing():
    dirty = "first made up line\x00\x07\r\nsecond \ud800line   \rthird made up line"
    text = sl.record_text(rec(plain=dirty))
    assert "\x00" not in text and "\x07" not in text and "\r" not in text
    assert "\ud800" not in text
    assert text.split("\n") == ["first made up line", "second ?line", "third made up line"]


def test_plain_text_falls_back_to_timed_text():
    r = rec(plain="", synced="[00:01.00]first made up line\n[00:04.00]second made up line")
    assert sl.record_text(r) == "first made up line\nsecond made up line"


# ------------------------------------------------------------------ names
@pytest.mark.parametrize("record_artist,artist,ok", [
    ("Aimer", "AI", False),           # a short name inside a longer one is not the same artist
    ("AI", "Aimer", False),
    ("Singer & Friend", "Singer", True),  # a duet credited to one of them
    ("Mr. Children", "Mr.Children", True),
    ("岡田有希子", "岡田 有希子", True),
    ("Yukiko Okada", "岡田有希子", False),
])
def test_artist_rule(record_artist, artist, ok):
    assert sl._artist_ok(record_artist, artist) is ok


@pytest.mark.parametrize("record_title,title,ok", [
    ("Song 2", "Song", False),
    ("Love Song", "Love", False),
    ("-Dreaming Girl- 恋、はじめまして", "Dreaming Girl- 恋、はじめまして", True),
    ("愛…illusion", "愛...illusion", True),
])
def test_title_rule(record_title, title, ok):
    assert sl._title_ok(record_title, title) is ok


@pytest.mark.parametrize("title,flags", [
    ("Song (インスト)", (True, False)),
    ("Song (オフボーカル)", (True, False)),
    ("Song (Inst)", (True, False)),
    ("Song [inst]", (True, False)),
    ("노래 (반주)", (True, False)),
    ("歌 (伴奏)", (True, False)),
    ("Song (TVサイズ)", (False, True)),
    ("Song -TV Size Ver.-", (False, True)),
    ("Song (Short Ver.)", (False, True)),
    ("Instinct", (False, False)),
    ("Song", (False, False)),
])
def test_version_words_in_several_languages(title, flags):
    assert sl.version_flags(title) == flags


# ------------------------------------------------------------------ odd server answers never raise
@pytest.mark.parametrize("payload", [
    {"not": "a list"},
    ["a string", 3, None],
    [{"id": [1, 2], "trackName": "Song", "artistName": "Singer", "duration": 200, "plainLyrics": LYRIC}],
    [{"id": 1, "trackName": 123, "artistName": None, "duration": "abc", "plainLyrics": 5}],
    [{"id": 1, "trackName": "Song", "artistName": "Singer", "duration": True, "plainLyrics": LYRIC}],
    [{"id": 1, "trackName": "Song", "artistName": "Singer", "duration": 200, "plainLyrics": None,
      "syncedLyrics": {"x": 1}, "instrumental": "yes"}],
    [],
])
def test_odd_payloads_do_not_raise(monkeypatch, payload):
    monkeypatch.setattr(net, "request", lambda *a, **k: FakeResp(data=payload))
    result = sl.find("Song", "Singer", 200)
    assert result.status in (sl.FOUND, sl.NOT_FOUND)
    assert isinstance(result.text, str)


def test_list_id_still_finds_the_record(monkeypatch):
    payload = [{"id": [1], "trackName": "Song", "artistName": "Singer", "duration": 200, "plainLyrics": LYRIC}]
    monkeypatch.setattr(net, "request", lambda *a, **k: FakeResp(data=payload))
    found = sl.find("Song", "Singer", 200)
    assert found.status == sl.FOUND and found.record_id is None


class BadJson(FakeResp):
    def json(self):
        raise ValueError("not json")


@pytest.mark.parametrize("resp,status", [
    (BadJson(), sl.BUSY),
    (FakeResp(500), sl.BUSY),
    (FakeResp(404), sl.NOT_FOUND),
])
def test_http_trouble(monkeypatch, resp, status):
    monkeypatch.setattr(net, "request", lambda *a, **k: resp)
    assert sl.find("Song", "Singer", 200).status == status


@pytest.mark.parametrize("length", [0, None, "abc", -5])
def test_no_length_means_no_lookup(monkeypatch, length):
    monkeypatch.setattr(net, "request", lambda *a, **k: pytest.fail("no request expected"))
    assert sl.find("Song", "Singer", length).status == sl.NOT_FOUND


@pytest.mark.parametrize("title,artist", [("   ", "Singer"), ("Song", "  "), (None, "Singer"), ("Song", None)])
def test_blank_names_need_tags(monkeypatch, title, artist):
    monkeypatch.setattr(net, "request", lambda *a, **k: pytest.fail("no request expected"))
    assert sl.find(title, artist, 200).status == sl.NEED_TAGS


def test_cancel_before_asking(monkeypatch):
    import threading

    ev = threading.Event()
    ev.set()
    monkeypatch.setattr(net, "request", lambda *a, **k: pytest.fail("no request expected"))
    assert sl.find("Song", "Singer", 200, cancel=ev).status == sl.BUSY


# ------------------------------------------------------------------ a lone record with far too much text
LONG = "\n".join(f"made up line number {i} with quite a few words in it" for i in range(60))  # ~2400 letters


def test_lone_record_too_long_for_the_song_is_rejected():
    # an 87 s intro carried another song's whole lyrics: one record, no timestamps
    assert sl.pick([rec(plain=LONG, duration=87.0)], "Song", "Singer", 87)[0] == sl.NOT_FOUND


def test_lone_record_of_normal_length_is_kept():
    assert sl.pick([rec(plain=LONG, duration=240.0)], "Song", "Singer", 240)[0] == sl.FOUND


@pytest.mark.parametrize("records", [
    [rec(rid=1, plain=LONG, duration=87.0, synced="[00:01.00]x\n[01:20.00]" + LONG.replace("\n", " "))],
    [rec(rid=1, plain=LONG, duration=87.0), rec(rid=2, plain=LONG + "\nla", duration=87.0)],
])
def test_density_check_only_for_records_nothing_vouches_for(records):
    # timestamps or a second record are checks of their own; fast rap must not be lost
    assert sl.pick(records, "Song", "Singer", 87)[0] == sl.FOUND


# ------------------------------------------------------------------ romanised copies of a Japanese lyric
ROMAJI = "\n".join(["kimi no koe ga kikoeru yo", "mirai e tsuzuku michi wo", "futari de aruite yuku", "kokoro no naka de"] * 6)
ENGLISH = "\n".join(["you can hold my hand tonight", "when the city lights are bright", "we will dance until the end",
                     "never letting go my friend"] * 6)
JAPANESE = "\n".join(["君の声が聞こえるよ", "未来へ続く道を", "二人で歩いてゆく", "心の中で"] * 6)


def test_romanised_text_is_told_from_english():
    assert sl.is_romanised(ROMAJI)
    assert not sl.is_romanised(ENGLISH)
    assert not sl.is_romanised(JAPANESE)


def test_original_script_wins_over_its_romanisation():
    # they tell the same lyric but share no letters: without this the song was a CONFLICT
    status, r = sl.pick([rec(rid=1, plain=JAPANESE), rec(rid=2, plain=ROMAJI)], "Song", "Singer", 200)
    assert status == sl.FOUND and r["id"] == 1


def test_romanised_only_is_still_used():
    status, r = sl.pick([rec(rid=2, plain=ROMAJI)], "Song", "Singer", 200)
    assert status == sl.FOUND and r["id"] == 2


def test_english_record_is_not_dropped_as_romanisation():
    # an English text next to a Japanese one is a real disagreement, not a transliteration
    assert sl.pick([rec(rid=1, plain=JAPANESE), rec(rid=2, plain=ENGLISH)], "Song", "Singer", 200)[0] == sl.CONFLICT


# ------------------------------------------------------------------ lyrics tags that hold only a note
@pytest.mark.parametrize("text,note", [
    ("[COWON S9]", "[COWON S9]"),   # seen in a Korean library: player markers, not lyrics
    ("[COWON A3]", "[COWON A3]"),
    ("[3 LINES]", "[3 LINES]"),
    ("  [M_CITY]\n", "[M_CITY]"),
    ("(Instrumental)", "(Instrumental)"),
    ("", ""),
    (LYRIC, ""),
    ("[00:01.00]made up timed line one\n[00:04.00]made up timed line two", ""),
])
def test_marker_only(text, note):
    assert sl.marker_only(text) == note


def _put_marker(path: str) -> None:
    """A marker the way a COWON player leaves it; in mp3 a USLT frame with an empty
    language and ")" as description, as found in a real library."""
    if path.endswith(".mp3"):
        from mutagen.id3 import ID3, USLT
        tags.write_file(path, tags.Tags(title="T", artist="A"))
        id3 = ID3(path)
        id3.add(USLT(encoding=0, lang="\x00\x00\x00", desc=")", text="[COWON S9]"))
        id3.save(path, v2_version=3)
    else:
        tags.write_file(path, tags.Tags(title="T", artist="A"), lyrics="[COWON S9]")


def test_marker_tag_is_replaced_and_undo_restores_it(sample):
    # the user's decision: a marker-only tag counts as empty, lyrics found replace it
    _put_marker(sample)
    assert sl.marker_only(tags.read_file(sample).lyrics) == "[COWON S9]"
    before = open(sample, "rb").read()
    tags.make_backup(sample)
    tags.write_file(sample, tags.Tags(title="T", artist="A"), lyrics=LYRIC)
    assert tags.read_file(sample).lyrics == LYRIC
    if sample.endswith(".mp3"):
        from mutagen.id3 import ID3
        assert len(ID3(sample).getall("USLT")) == 1  # the marker frame is gone, not kept beside
    assert tags.restore_backup(sample) is True
    assert open(sample, "rb").read() == before
    assert tags.read_file(sample).lyrics == "[COWON S9]"


# ------------------------------------------------------------------ writing what the server sent
@pytest.fixture(params=NAMES)
def sample(request, tmp_path):
    _ensure_fixtures()
    dst = tmp_path / request.param
    shutil.copy(os.path.join(FIXTURES, request.param), dst)
    return str(dst)


def test_cleaned_server_text_writes_to_every_format(sample):
    text = sl.record_text(rec(plain="first \ud83c line 🎵 ok\x00\r\n二行目のテキスト\r\n세 번째 줄 텍스트"))
    tags.write_file(sample, tags.Tags(title="T", artist="A"), lyrics=text)
    assert tags.read_file(sample).lyrics == text


def test_long_lyrics_round_trip(sample):
    text = "\n".join(f"made up line {i} with some words" for i in range(800))  # ~25k chars
    tags.write_file(sample, tags.Tags(title="T", artist="A"), lyrics=text)
    assert tags.read_file(sample).lyrics == text
