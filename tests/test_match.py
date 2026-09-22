"""Scoring, merging, file-name guessing and settings validation (no network)."""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import match  # noqa: E402
import search_acoustid  # noqa: E402
import search_itunes  # noqa: E402
import search_mb  # noqa: E402
from match import SOURCE_ITUNES, SOURCE_MB, Candidate  # noqa: E402


def test_guess_from_filename():
    assert match.guess_from_filename(r"C:\m\01. IU - Good Day (Official MV).mp3") == ("IU", "Good Day")
    assert match.guess_from_filename("track01.mp3") == ("", "track01")
    assert match.guess_from_filename("Some_Song.flac") == ("", "Some Song")


def test_generic_names():
    assert match.is_generic_name("track01")
    assert match.is_generic_name("07")
    assert match.is_generic_name("Untitled 3")
    assert not match.is_generic_name("Good Day")
    assert not match.is_generic_name("track01", "IU")


def test_score_prefers_exact_title_and_length():
    good = Candidate(title="Good Day", artist="IU", length=233.0, sources=[SOURCE_ITUNES])
    other = Candidate(title="Good Day", artist="Someone Else", length=190.0, sources=[SOURCE_MB])
    assert match.score(good, "Good Day", "IU", 233.5) >= 90
    assert match.score(other, "Good Day", "IU", 233.5) < match.score(good, "Good Day", "IU", 233.5)


def test_length_penalty_beyond_five_seconds():
    a = Candidate(title="X", artist="Y", length=200.0, sources=[SOURCE_MB])
    b = Candidate(title="X", artist="Y", length=210.0, sources=[SOURCE_MB])
    assert match.score(a, "X", "Y", 200.0) > match.score(b, "X", "Y", 200.0)


def test_merge_same_recording_from_two_sources():
    a = Candidate(title="Good Day", artist="IU", album="Real", length=233.0, sources=[SOURCE_ITUNES], cover_url="u")
    b = Candidate(title="good day", artist="iu", album="Real", length=233.5, sources=[SOURCE_MB], mb_release_id="r")
    merged = match.merge([a, b])
    assert len(merged) == 1
    assert merged[0].sources == [SOURCE_ITUNES, SOURCE_MB]
    assert merged[0].cover_url == "u" and merged[0].mb_release_id == "r"


def test_merge_keeps_disagreeing_rows():
    a = Candidate(title="Good Day", artist="IU", album="Real", sources=[SOURCE_ITUNES])
    b = Candidate(title="Good Day", artist="IU", album="Live 2012", sources=[SOURCE_MB])
    assert len(match.merge([a, b])) == 2


def test_rank_sorts_by_score():
    cands = [
        Candidate(title="Other", artist="IU", length=100.0, sources=[SOURCE_MB]),
        Candidate(title="Good Day", artist="IU", length=233.0, sources=[SOURCE_ITUNES]),
    ]
    ranked = match.rank(cands, "Good Day", "IU", 233.0)
    assert ranked[0].title == "Good Day"


def test_itunes_parsing():
    item = {"wrapperType": "track", "trackName": "Good Day", "artistName": "IU", "collectionName": "Real",
            "releaseDate": "2010-12-09T08:00:00Z", "trackNumber": 3, "primaryGenreName": "K-Pop",
            "trackTimeMillis": 233520, "artworkUrl100": "https://x/100x100bb.jpg", "trackId": 1}
    c = search_itunes._candidate(item)
    assert (c.title, c.artist, c.album, c.year, c.track, c.genre) == ("Good Day", "IU", "Real", "2010", "3", "K-Pop")
    assert c.length == 233.52 and c.cover_url.endswith("1000x1000bb.jpg")


def test_mb_parsing_prefers_official_album():
    rec = {"id": "rid", "title": "Good Day", "length": 233520,
           "artist-credit": [{"name": "IU", "joinphrase": " feat. ", "artist": {"name": "IU"}}, {"name": "X"}],
           "releases": [
               {"id": "single", "title": "Good Day", "status": "Official", "date": "2010-12-01",
                "release-group": {"primary-type": "Single"}, "media": [{"track": [{"number": "1"}]}]},
               {"id": "album", "title": "Real", "status": "Official", "date": "2010-12-09",
                "release-group": {"primary-type": "Album"}, "media": [{"track": [{"number": "3"}]}]},
           ]}
    c = search_mb.candidate_from_recording(rec)
    assert c.artist == "IU feat. X"
    assert c.album == "Real" and c.year == "2010" and c.track == "3"
    assert c.cover_url == "https://coverartarchive.org/release/album/front-500"


def test_mb_query_escaping():
    q = search_mb.build_query('Good (Day)', 'IU: Live')
    assert q == 'recording:"Good \\(Day\\)" AND artist:"IU\\: Live"'


def test_acoustid_parsing():
    rec = {"id": "rid", "title": "Good Day", "duration": 233, "artists": [{"name": "IU"}],
           "releases": [{"id": "rel", "title": "Real", "date": {"year": 2010},
                         "mediums": [{"tracks": [{"position": 3}]}]}]}
    c = search_acoustid._candidate(rec, 0.97)
    assert c.album == "Real" and c.year == "2010" and c.track == "3" and c.acoustid_score == 0.97
    assert match.score(c, "", "", 233.0) >= 90


def test_prefs_ignore_wrong_types(tmp_path, monkeypatch):
    import i18n
    import prefs

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"country": 5, "rename": "yes", "cover_max_px": 10, "acoustid_key": ["k"]}), encoding="utf-8")
    monkeypatch.setattr(i18n, "SETTINGS_PATH", str(path))
    p = prefs.load()
    assert p.country == "" and p.rename is False and p.cover_max_px == 1000 and p.acoustid_key == ""
    path.write_text("{not json", encoding="utf-8")
    assert prefs.load() == prefs.Prefs()


def test_apply_candidate_fill_gaps_vs_overwrite():
    import pipeline
    import tags

    cur = tags.Tags(title="A", artist="B", album="Best Album", year="2026", track="3/24")
    cand = Candidate(title="A", artist="B", album="Orig Album", year="2017", track="1", genre="Pop")
    filled = pipeline.apply_candidate(cur, cand, overwrite=False)
    assert (filled.album, filled.year, filled.track, filled.genre) == ("Best Album", "2026", "3/24", "Pop")
    over = pipeline.apply_candidate(cur, cand, overwrite=True)
    assert (over.album, over.year, over.track) == ("Orig Album", "2017", "1")
