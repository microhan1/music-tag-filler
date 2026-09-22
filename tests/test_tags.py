"""Tag write / backup / byte-exact undo on all four formats.

    python -m pytest tests

Fixtures are generated into tests/fixtures by samples/make_samples.py
(needs soundfile + numpy); the m4a is a silent container built by hand.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tags  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures")
NAMES = ("sample-a.mp3", "sample-b.flac", "sample-c.ogg", "sample-d.m4a")


def _ensure_fixtures() -> None:
    if all(os.path.exists(os.path.join(FIXTURES, n)) for n in NAMES):
        return
    subprocess.run([sys.executable, os.path.join(ROOT, "samples", "make_samples.py"), FIXTURES, "--m4a"], check=True)


def _sha(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _cover_png(size: int = 1400) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (size, size), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture(params=NAMES)
def sample(request, tmp_path):
    _ensure_fixtures()
    dst = tmp_path / request.param
    shutil.copy(os.path.join(FIXTURES, request.param), dst)
    return str(dst)


def test_read_untagged(sample):
    info = tags.read_file(sample)
    assert info.fmt in ("MP3", "FLAC", "OGG", "M4A")
    assert info.tags.is_empty()
    assert info.cover is None
    assert info.length > 1.0


def test_write_read_roundtrip(sample):
    cover, mime = tags.prepare_cover(_cover_png())
    new = tags.Tags(title="Good Day", artist="IU", album="Real", album_artist="IU", year="2010", track="3/6", genre="K-Pop")
    tags.write_file(sample, new, cover, mime)
    info = tags.read_file(sample)
    assert info.tags == new
    assert info.cover == cover
    assert info.cover_mime == "image/jpeg"


def test_empty_fields_are_removed(sample):
    tags.write_file(sample, tags.Tags(title="A", artist="B", genre="Pop"))
    tags.write_file(sample, tags.Tags(title="A"))
    info = tags.read_file(sample)
    assert info.tags.artist == "" and info.tags.genre == ""


def test_backup_then_undo_is_byte_exact(sample):
    before = _sha(sample)
    backup = tags.make_backup(sample)
    record = json.load(open(backup, encoding="utf-8"))
    assert record["layout"] is not None
    cover, mime = tags.prepare_cover(_cover_png())
    tags.write_file(sample, tags.Tags(title="T", artist="A", album="L"), cover, mime)
    assert _sha(sample) != before
    # a second save keeps the first backup (the original)
    tags.make_backup(sample)
    assert json.load(open(backup, encoding="utf-8"))["sha256"] == record["sha256"]
    assert tags.restore_backup(sample) is True
    assert _sha(sample) == before


def test_undo_after_tagged_original(sample):
    """Undo must also work when the original already had tags and a cover."""
    cover, mime = tags.prepare_cover(_cover_png(300))
    tags.write_file(sample, tags.Tags(title="Orig", artist="Someone", year="1999"), cover, mime)
    before = _sha(sample)
    tags.make_backup(sample)
    tags.write_file(sample, tags.Tags(title="New"), None)
    assert tags.restore_backup(sample) is True
    assert _sha(sample) == before
    assert tags.read_file(sample).tags.title == "Orig"


def test_undo_without_backup(sample):
    with pytest.raises(tags.NoBackup):
        tags.restore_backup(sample)


def test_prepare_cover_shrinks_and_keeps_small_jpeg():
    from PIL import Image

    data, mime = tags.prepare_cover(_cover_png(1400), max_px=1000)
    assert mime == "image/jpeg"
    assert max(Image.open(io.BytesIO(data)).size) == 1000
    again, _ = tags.prepare_cover(data, max_px=1000)
    assert again == data  # already a small JPEG: untouched


def test_rename_target(tmp_path):
    p = tmp_path / "x.mp3"
    p.write_bytes(b"")
    target = tags.rename_target(str(p), tags.Tags(title="Good: Day?", artist="IU/Lee"))
    assert os.path.basename(target) == "IU_Lee - Good_ Day_.mp3"
    (tmp_path / "IU_Lee - Good_ Day_.mp3").write_bytes(b"")
    target2 = tags.rename_target(str(p), tags.Tags(title="Good: Day?", artist="IU/Lee"))
    assert os.path.basename(target2) == "IU_Lee - Good_ Day_ (2).mp3"
    assert tags.rename_target(str(p), tags.Tags()) is None


def test_collect_files(tmp_path):
    (tmp_path / "a.MP3").write_bytes(b"")
    (tmp_path / "b.txt").write_bytes(b"")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.flac").write_bytes(b"")
    found = tags.collect_files([str(tmp_path), str(tmp_path / "a.MP3")])
    assert [os.path.basename(p) for p in found] == ["a.MP3", "c.flac"]
    assert [os.path.basename(p) for p in tags.collect_files([str(tmp_path)], recurse=False)] == ["a.MP3"]


def test_read_garbage_raises(tmp_path):
    p = tmp_path / "bad.mp3"
    p.write_bytes(b"not audio at all" * 100)
    with pytest.raises(tags.UnsupportedFile):
        tags.read_file(str(p))
    p2 = tmp_path / "empty.flac"
    p2.write_bytes(b"")
    with pytest.raises(tags.UnsupportedFile):
        tags.read_file(str(p2))
