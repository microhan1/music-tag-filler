"""A save never leaves a change without its backup beside the file (LESSONS A13).

A file held open stands in for a lock by another program: on Windows an open
file cannot be renamed.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pipeline  # noqa: E402
import prefs  # noqa: E402
import tags  # noqa: E402
from test_tags import FIXTURES, _ensure_fixtures  # noqa: E402

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="relies on Windows refusing to rename an open file")
NEW = tags.Tags(title="Title", artist="Artist")


@pytest.fixture
def song(tmp_path):
    _ensure_fixtures()
    dst = tmp_path / "01 track.mp3"
    shutil.copy(os.path.join(FIXTURES, "sample-a.mp3"), dst)
    return str(dst)


def _sha(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def test_rename_moves_file_and_backup_together(song, tmp_path):
    res = pipeline.save_file(song, NEW, None, prefs.Prefs(), rename=True)
    assert res.renamed and not res.rename_failed
    assert sorted(os.listdir(tmp_path)) == ["Artist - Title.mp3", "Artist - Title.mp3.tagbak.json"]
    assert res.backup == tags.backup_path(res.path)


def test_backup_in_use_keeps_both_names_and_undo_works(song, tmp_path):
    before = _sha(song)
    tags.make_backup(song)
    with open(tags.backup_path(song), "rb"):
        res = pipeline.save_file(song, NEW, None, prefs.Prefs(), rename=True)
    assert res.rename_failed and not res.renamed and res.path == song
    assert res.backup == tags.backup_path(song)
    assert sorted(os.listdir(tmp_path)) == ["01 track.mp3", "01 track.mp3.tagbak.json"]
    assert tags.read_file(song).tags.title == "Title"  # the tags were saved
    assert tags.restore_backup(song) is True and _sha(song) == before


def test_file_in_use_puts_the_backup_back(song, tmp_path):
    before = _sha(song)
    with open(song, "rb"):
        res = pipeline.save_file(song, NEW, None, prefs.Prefs(), rename=True)
    assert res.rename_failed and res.path == song and res.backup == tags.backup_path(song)
    assert sorted(os.listdir(tmp_path)) == ["01 track.mp3", "01 track.mp3.tagbak.json"]
    assert tags.restore_backup(song) is True and _sha(song) == before


def test_rollback_failure_reports_where_the_backup_is(song, tmp_path, monkeypatch):
    tags.make_backup(song)
    target = str(tmp_path / "Artist - Title.mp3")
    real, calls = os.replace, []

    def replace(src, dst):
        calls.append(src)
        if len(calls) >= 2:  # the file itself, then putting the backup back
            raise PermissionError(13, "in use", src)
        real(src, dst)

    monkeypatch.setattr(tags.os, "replace", replace)
    with pytest.raises(tags.RenameFailed) as info:
        tags.rename_file(song, target)
    assert info.value.backup == tags.backup_path(target) and os.path.exists(info.value.backup)


def test_unreadable_backup_stops_the_save(song):
    with open(tags.backup_path(song), "w", encoding="utf-8") as f:
        f.write("{ broken")
    before = _sha(song)
    with pytest.raises(tags.BrokenBackup):
        pipeline.save_file(song, NEW, None, prefs.Prefs(), rename=True)
    assert _sha(song) == before and os.path.exists(song)


def test_rename_target_skips_a_leftover_backup(song, tmp_path):
    (tmp_path / "Artist - Title.mp3.tagbak.json").write_text("{}", encoding="utf-8")
    assert os.path.basename(tags.rename_target(song, NEW)) == "Artist - Title (2).mp3"
