"""Artist / album / recording identifiers: written per format, kept across
saves, restored by undo, and parsed from each source (no network)."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys

import pytest
from mutagen.flac import FLAC
from mutagen.id3 import ID3
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import match  # noqa: E402
import pipeline  # noqa: E402
import search_acoustid  # noqa: E402
import search_itunes  # noqa: E402
import search_mb  # noqa: E402
import tags  # noqa: E402
from match import Candidate  # noqa: E402
from tests.test_tags import FIXTURES, NAMES, _ensure_fixtures  # noqa: E402

A1 = "4a1560cf-67e4-44f7-b99a-fcf84defc831"
A2 = "130d679a-9a57-4d1f-b2a5-f4b8c5a6b0aa"
REL = "2a9963b5-dad8-4436-85b4-41a02e7ad30b"
REC = "c461e36e-7a60-4cc2-b0cd-eda584443503"
FULL = tags.Ids(mb_artist_ids=[A1, A2], mb_album_artist_ids=[A1], mb_album_id=REL, mb_recording_id=REC,
                artist_sort="Okada, Yukiko with Hatsune, Miku", album_artist_sort="Okada, Yukiko",
                itunes_artist_id="275749278")


def _sha(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


@pytest.fixture(params=NAMES)
def sample(request, tmp_path):
    _ensure_fixtures()
    dst = tmp_path / request.param
    shutil.copy(os.path.join(FIXTURES, request.param), dst)
    return str(dst)


def test_untagged_file_has_no_ids(sample):
    assert tags.read_file(sample).ids.is_empty()


def test_ids_roundtrip_every_format(sample):
    tags.write_file(sample, tags.Tags(title="T", artist="A"), ids=FULL)
    assert tags.read_file(sample).ids == FULL


def test_ids_survive_a_later_save_without_ids(sample):
    """A second save (say, the user fixes the title) must not drop the identity
    tags; for mp3 that includes TSOP, which the v2.3 conversion removes."""
    tags.write_file(sample, tags.Tags(title="T", artist="A"), ids=FULL)
    tags.write_file(sample, tags.Tags(title="T2", artist="A"))
    info = tags.read_file(sample)
    assert info.tags.title == "T2" and info.ids == FULL


def test_new_ids_merge_over_existing(sample):
    tags.write_file(sample, tags.Tags(title="T"), ids=tags.Ids(itunes_artist_id="42"))
    tags.write_file(sample, tags.Tags(title="T"), ids=tags.Ids(mb_artist_ids=[A1], artist_sort="Okada, Yukiko"))
    ids = tags.read_file(sample).ids
    assert ids.itunes_artist_id == "42" and ids.mb_artist_ids == [A1] and ids.artist_sort == "Okada, Yukiko"


def test_tag_names_follow_picard(tmp_path):
    _ensure_fixtures()
    paths = {}
    for name in NAMES:
        dst = tmp_path / name
        shutil.copy(os.path.join(FIXTURES, name), dst)
        tags.write_file(str(dst), tags.Tags(title="T"), ids=FULL)
        paths[os.path.splitext(name)[1]] = str(dst)

    id3 = ID3(paths[".mp3"])
    assert id3.version[:2] == (2, 3)
    assert id3["TXXX:MusicBrainz Artist Id"].text == [f"{A1}/{A2}"]  # v2.3: one value, joined
    assert id3["TXXX:MusicBrainz Album Artist Id"].text == [A1]
    assert id3["TXXX:MusicBrainz Album Id"].text == [REL]
    assert id3["TXXX:iTunes Artist Id"].text == ["275749278"]
    assert id3["UFID:http://musicbrainz.org"].data == REC.encode("ascii")  # recording ID is a UFID, not a TXXX
    assert "TXXX:MusicBrainz Track Id" not in id3
    assert id3["TSOP"].text == ["Okada, Yukiko with Hatsune, Miku"] and id3["TSO2"].text == ["Okada, Yukiko"]

    for path, cls in ((paths[".flac"], FLAC), (paths[".ogg"], OggVorbis)):
        vc = cls(path).tags
        assert vc["MUSICBRAINZ_ARTISTID"] == [A1, A2]  # two separate values
        assert vc["MUSICBRAINZ_ALBUMARTISTID"] == [A1] and vc["MUSICBRAINZ_ALBUMID"] == [REL]
        assert vc["MUSICBRAINZ_TRACKID"] == [REC]
        assert vc["ARTISTSORT"] == ["Okada, Yukiko with Hatsune, Miku"] and vc["ALBUMARTISTSORT"] == ["Okada, Yukiko"]
        assert vc["ITUNES_ARTISTID"] == ["275749278"]

    mp4 = MP4(paths[".m4a"]).tags
    assert [bytes(v).decode() for v in mp4["----:com.apple.iTunes:MusicBrainz Artist Id"]] == [A1, A2]
    assert bytes(mp4["----:com.apple.iTunes:MusicBrainz Album Id"][0]).decode() == REL
    assert bytes(mp4["----:com.apple.iTunes:MusicBrainz Track Id"][0]).decode() == REC
    assert bytes(mp4["----:com.apple.iTunes:iTunes Artist Id"][0]).decode() == "275749278"
    assert mp4["soar"] == ["Okada, Yukiko with Hatsune, Miku"] and mp4["soaa"] == ["Okada, Yukiko"]


def test_undo_after_ids_is_byte_exact(sample):
    before = _sha(sample)
    tags.make_backup(sample)
    tags.write_file(sample, tags.Tags(title="T", artist="A"), ids=FULL)
    assert _sha(sample) != before
    assert tags.restore_backup(sample) is True
    assert _sha(sample) == before and tags.read_file(sample).ids.is_empty()


def test_tag_level_undo_removes_ids_too(sample):
    """When the byte layout cannot be used, undo falls back to rewriting tag
    values; the identity tags must go back to what the backup recorded."""
    tags.write_file(sample, tags.Tags(title="Orig"), ids=tags.Ids(itunes_artist_id="7"))
    backup = tags.make_backup(sample)
    record = json.load(open(backup, encoding="utf-8"))
    assert record["ids"]["itunes_artist_id"] == "7"
    record["layout"] = None  # force the fallback path
    json.dump(record, open(backup, "w", encoding="utf-8"))
    tags.write_file(sample, tags.Tags(title="New"), ids=FULL)
    assert tags.restore_backup(sample) is False
    info = tags.read_file(sample)
    assert info.tags.title == "Orig" and info.ids == tags.Ids(itunes_artist_id="7")


def test_old_backups_without_ids_still_restore(sample):
    backup = tags.make_backup(sample)
    record = json.load(open(backup, encoding="utf-8"))
    del record["ids"]
    record["layout"] = None
    json.dump(record, open(backup, "w", encoding="utf-8"))
    tags.write_file(sample, tags.Tags(title="New"))
    assert tags.restore_backup(sample) is False


# ------------------------------------------------------------------ sources
def _mb_recording() -> dict:
    return {
        "id": REC, "title": "Song", "length": 200000,
        "artist-credit": [
            {"name": "岡田有希子", "joinphrase": " with ", "artist": {
                "id": A1, "name": "岡田有希子", "sort-name": "Okada, Yukiko",
                "aliases": [{"name": "Yukiko Okada", "locale": None, "primary": None}]}},
            {"name": "初音ミク", "artist": {
                "id": A2, "name": "初音ミク", "sort-name": "Hatsune, Miku",
                "aliases": [{"name": "Hatsune Miku", "locale": "en", "primary": True}]}},
        ],
        "releases": [{"id": REL, "title": "Album", "status": "Official", "date": "1986-01-01",
                      "release-group": {"id": "rg", "primary-type": "Album"},
                      "artist-credit": [{"name": "IU", "artist": {"id": A1, "name": "IU", "sort-name": "IU"}}]}],
    }


def test_mb_candidate_carries_ids_and_sort_names():
    c = search_mb.candidate_from_recording(_mb_recording())
    assert c.mb_artist_ids == [A1, A2] and c.mb_album_artist_ids == [A1]
    assert c.artist_sort == "Okada, Yukiko with Hatsune, Miku" and c.album_artist_sort == "IU"
    assert c.mb_recording_id == REC and c.mb_release_id == REL


def test_latin_name_only_when_stated_clearly():
    c = search_mb.candidate_from_recording(_mb_recording())
    # the first artist has a Latin alias but no locale: not clear enough, so no Latin credit at all
    assert c.artist_latin == ""
    assert c.album_artist_latin == "IU"  # already Latin script
    rec = _mb_recording()
    rec["artist-credit"][0]["artist"]["aliases"] = [{"name": "Yukiko Okada", "locale": "en", "primary": True}]
    assert search_mb.candidate_from_recording(rec).artist_latin == "Yukiko Okada with Hatsune Miku"


def test_itunes_and_acoustid_candidates_carry_ids():
    it = search_itunes._candidate({"wrapperType": "track", "trackName": "S", "artistName": "A", "artistId": 275749278,
                                   "trackId": 1, "artworkUrl100": "https://x/100x100bb.jpg"})
    assert it.itunes_artist_id == "275749278" and it.mb_artist_ids == []
    ac = search_acoustid._candidate({"id": REC, "title": "S", "artists": [{"id": A1, "name": "A"}],
                                     "releases": [{"id": REL, "title": "L", "artists": [{"id": A2, "name": "B"}]}]}, 0.9)
    assert ac.mb_artist_ids == [A1] and ac.mb_album_artist_ids == [A2]


def test_ids_from_candidate_and_merged_candidate():
    mb = search_mb.candidate_from_recording(_mb_recording())
    it = Candidate(title="Song", artist="岡田有希子 with 初音ミク", album="Album", length=200.0,
                   sources=[match.SOURCE_ITUNES], itunes_artist_id="275749278")
    merged = match.merge([it, mb])
    assert len(merged) == 1
    ids = pipeline.ids_from_candidate(merged[0])
    assert ids.itunes_artist_id == "275749278" and ids.mb_artist_ids == [A1, A2]  # both sources' identity
    assert ids.mb_album_id == REL and ids.mb_recording_id == REC
    only_itunes = pipeline.ids_from_candidate(it)
    assert only_itunes.itunes_artist_id == "275749278" and not only_itunes.mb_artist_ids  # MusicBrainz left empty


def test_artist_name_preference():
    rec = _mb_recording()
    rec["artist-credit"][0]["artist"]["aliases"] = [{"name": "Yukiko Okada", "locale": "en", "primary": True}]
    c = search_mb.candidate_from_recording(rec)
    original = pipeline.apply_candidate(tags.Tags(), c, overwrite=True)
    latin = pipeline.apply_candidate(tags.Tags(), c, overwrite=True, latin=True)
    assert original.artist == "岡田有希子 with 初音ミク"
    assert latin.artist == "Yukiko Okada with Hatsune Miku"


def test_prefs_artist_name_preference_is_validated(tmp_path, monkeypatch):
    import i18n
    import prefs

    path = tmp_path / "settings.json"
    monkeypatch.setattr(i18n, "SETTINGS_PATH", str(path))
    assert prefs.load().artist_name_preference == "original"
    path.write_text(json.dumps({"artist_name_preference": "LATIN"}), encoding="utf-8")
    assert prefs.load().artist_name_preference == "latin"
    path.write_text(json.dumps({"artist_name_preference": "romaji"}), encoding="utf-8")
    assert prefs.load().artist_name_preference == "original"
    path.write_text(json.dumps({"artist_name_preference": 3}), encoding="utf-8")
    assert prefs.load().artist_name_preference == "original"


def test_save_file_writes_ids(sample):
    import prefs

    res = pipeline.save_file(sample, tags.Tags(title="T", artist="A"), None, prefs.Prefs(), ids=FULL)
    assert tags.read_file(res.path).ids == FULL
    assert os.path.exists(res.backup)
