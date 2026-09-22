"""Tag reading, writing, backup and undo for mp3 / flac / m4a / ogg (mutagen).

Nothing here touches a file until write_file() or restore_backup() is
called. Before the first write, make_backup() stores the original tags AND
the raw bytes of the file's non-audio regions in <file>.tagbak.json, so
undo can rebuild the original file byte for byte. If the layout of the
file is not understood, the backup still holds the tag values and undo
falls back to rewriting those.
"""
from __future__ import annotations

import base64
import dataclasses
import hashlib
import io
import json
import os
import re
import struct
import time
import zlib

import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, TALB, TCON, TDRC, TIT2, TPE1, TPE2, TRCK, ID3NoHeaderError
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover
from mutagen.ogg import OggPage
from mutagen.oggvorbis import OggVorbis

FORMATS = {".mp3": "MP3", ".flac": "FLAC", ".m4a": "M4A", ".ogg": "OGG"}
SUPPORTED_EXTS = tuple(FORMATS)
FIELDS = ("title", "artist", "album", "album_artist", "year", "track", "genre")
BACKUP_SUFFIX = ".tagbak.json"
BACKUP_VERSION = 1
COVER_MAX_PX_DEFAULT = 1000
COVER_JPEG_QUALITY = 85
COVER_KEEP_LIMIT = 5 * 1024 * 1024  # larger covers are always re-encoded


class UnsupportedFile(Exception):
    pass


class FileLocked(Exception):
    """Read-only, in use, or otherwise not writable."""


class NoBackup(Exception):
    pass


@dataclasses.dataclass
class Tags:
    title: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    year: str = ""
    track: str = ""
    genre: str = ""

    def as_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Tags":
        return cls(**{f: str(data.get(f) or "") for f in FIELDS})

    def is_empty(self) -> bool:
        return not (self.title or self.artist)


@dataclasses.dataclass
class FileInfo:
    path: str
    fmt: str
    length: float  # seconds
    bitrate: int  # kbps
    sample_rate: int
    tags: Tags
    cover: bytes | None
    cover_mime: str


# ------------------------------------------------------------------ files
def format_of(path: str) -> str | None:
    return FORMATS.get(os.path.splitext(path)[1].lower())


def collect_files(paths: list[str], recurse: bool = True) -> list[str]:
    """Expand folders, keep supported extensions, drop duplicates, keep order."""
    out: list[str] = []
    seen: set[str] = set()

    def add(p: str) -> None:
        key = os.path.normcase(os.path.abspath(p))
        if key not in seen and format_of(p):
            seen.add(key)
            out.append(os.path.abspath(p))

    for p in paths:
        if os.path.isdir(p):
            if recurse:
                for root, dirs, files in os.walk(p):
                    dirs.sort()
                    for name in sorted(files):
                        add(os.path.join(root, name))
            else:
                for name in sorted(os.listdir(p)):
                    full = os.path.join(p, name)
                    if os.path.isfile(full):
                        add(full)
        elif os.path.isfile(p):
            add(p)
    return out


def _open(path: str):
    fmt = format_of(path)
    if fmt is None:
        raise UnsupportedFile(path)
    try:
        if fmt == "MP3":
            return fmt, MP3(path)
        if fmt == "FLAC":
            return fmt, FLAC(path)
        if fmt == "M4A":
            return fmt, MP4(path)
        return fmt, OggVorbis(path)
    except PermissionError as exc:
        raise FileLocked(path) from exc
    except mutagen.MutagenError as exc:
        # mutagen wraps the OSError it hit while opening; a locked file is not a bad file
        if _is_permission_error(exc):
            raise FileLocked(path) from exc
        raise UnsupportedFile(f"{path}: {exc}") from exc


def _is_permission_error(exc: BaseException) -> bool:
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, OSError) and cur.errno in (13, 30):
            return True
        inner = cur.args[0] if cur.args else None
        if isinstance(inner, OSError) and inner.errno in (13, 30):
            return True
        cur = cur.__cause__ or cur.__context__
    return "Errno 13" in str(exc) or "Permission denied" in str(exc)


def read_file(path: str) -> FileInfo:
    fmt, audio = _open(path)
    info = audio.info
    length = float(getattr(info, "length", 0.0) or 0.0)
    bitrate = int(round((getattr(info, "bitrate", 0) or 0) / 1000))
    rate = int(getattr(info, "sample_rate", 0) or 0)
    if fmt == "MP3":
        tags, cover, mime = _read_id3(audio.tags)
    elif fmt == "FLAC":
        tags, cover, mime = _read_vorbis(audio.tags)
        pic = _front_picture(audio.pictures)
        if pic is not None:
            cover, mime = pic.data, pic.mime
    elif fmt == "M4A":
        tags, cover, mime = _read_mp4(audio.tags)
    else:
        tags, cover, mime = _read_vorbis(audio.tags)
        cover, mime = _read_vorbis_picture(audio.tags) if cover is None else (cover, mime)
    return FileInfo(os.path.abspath(path), fmt, length, bitrate, rate, tags, cover, mime)


def _text(frame) -> str:
    try:
        return str(frame.text[0]) if frame is not None and frame.text else ""
    except (AttributeError, IndexError):
        return ""


def _read_id3(id3) -> tuple[Tags, bytes | None, str]:
    if id3 is None:
        return Tags(), None, ""
    tags = Tags(
        title=_text(id3.get("TIT2")),
        artist=_text(id3.get("TPE1")),
        album=_text(id3.get("TALB")),
        album_artist=_text(id3.get("TPE2")),
        year=_text(id3.get("TDRC")) or _text(id3.get("TYER")),
        track=_text(id3.get("TRCK")),
        genre=_text(id3.get("TCON")),
    )
    # some rips carry several front covers; show the front one with the most pixels (largest data)
    pics = [f for f in id3.values() if f.FrameID == "APIC"]
    pics.sort(key=lambda f: (0 if getattr(f, "type", 0) == 3 else 1, -len(f.data or b"")))
    if pics:
        return tags, bytes(pics[0].data), str(pics[0].mime or "")
    return tags, None, ""


def _first(vc, key: str) -> str:
    try:
        values = vc.get(key) if vc is not None else None
        return str(values[0]) if values else ""
    except (KeyError, IndexError, TypeError):
        return ""


def _read_vorbis(vc) -> tuple[Tags, bytes | None, str]:
    tags = Tags(
        title=_first(vc, "title"),
        artist=_first(vc, "artist"),
        album=_first(vc, "album"),
        album_artist=_first(vc, "albumartist"),
        year=_first(vc, "date"),
        track=_first(vc, "tracknumber"),
        genre=_first(vc, "genre"),
    )
    return tags, None, ""


def _read_vorbis_picture(vc) -> tuple[bytes | None, str]:
    for b64 in (vc.get("metadata_block_picture") or []) if vc is not None else []:
        try:
            pic = Picture(base64.b64decode(b64))
        except Exception:
            continue
        if pic.data:
            return bytes(pic.data), str(pic.mime or "")
    return None, ""


def _front_picture(pictures) -> Picture | None:
    if not pictures:
        return None
    return sorted(pictures, key=lambda p: 0 if p.type == 3 else 1)[0]


def _read_mp4(mp4) -> tuple[Tags, bytes | None, str]:
    if mp4 is None:
        return Tags(), None, ""

    def s(key: str) -> str:
        v = mp4.get(key)
        return str(v[0]) if v else ""

    track = ""
    trkn = mp4.get("trkn")
    if trkn and isinstance(trkn[0], (tuple, list)) and trkn[0]:
        n, total = (list(trkn[0]) + [0, 0])[:2]
        track = f"{n}/{total}" if total else str(n) if n else ""
    tags = Tags(
        title=s("\xa9nam"), artist=s("\xa9ART"), album=s("\xa9alb"), album_artist=s("aART"),
        year=s("\xa9day"), track=track, genre=s("\xa9gen"),
    )
    covr = mp4.get("covr")
    if covr:
        fmt = getattr(covr[0], "imageformat", MP4Cover.FORMAT_JPEG)
        return tags, bytes(covr[0]), "image/png" if fmt == MP4Cover.FORMAT_PNG else "image/jpeg"
    return tags, None, ""


# ------------------------------------------------------------------ writing
def write_file(path: str, tags: Tags, cover: bytes | None = None, cover_mime: str = "image/jpeg") -> None:
    """Write the seven text fields; replace the cover when `cover` is given.
    Empty text fields are removed from the file."""
    fmt, audio = _open(path)
    try:
        if fmt == "MP3":
            _write_id3(audio, tags, cover, cover_mime)
        elif fmt == "FLAC":
            _write_flac(audio, tags, cover, cover_mime)
        elif fmt == "M4A":
            _write_mp4(audio, tags, cover, cover_mime)
        else:
            _write_ogg(audio, tags, cover, cover_mime)
    except PermissionError as exc:
        raise FileLocked(path) from exc
    except OSError as exc:
        if getattr(exc, "winerror", None) in (5, 32, 33) or exc.errno in (13, 30):
            raise FileLocked(path) from exc
        raise
    except mutagen.MutagenError as exc:
        raise FileLocked(f"{path}: {exc}") from exc


def _write_id3(mp3: MP3, tags: Tags, cover: bytes | None, mime: str) -> None:
    if mp3.tags is None:
        mp3.add_tags()
    id3: ID3 = mp3.tags
    frames = {
        "TIT2": (TIT2, tags.title), "TPE1": (TPE1, tags.artist), "TALB": (TALB, tags.album),
        "TPE2": (TPE2, tags.album_artist), "TDRC": (TDRC, tags.year), "TRCK": (TRCK, tags.track),
        "TCON": (TCON, tags.genre),
    }
    for key, (cls, value) in frames.items():
        id3.delall(key)
        if value:
            id3.add(cls(encoding=3, text=[value]))
    id3.delall("TYER")  # TDRC becomes TYER when converting to v2.3
    if cover is not None:
        id3.delall("APIC")
        id3.add(APIC(encoding=0, mime=mime, type=3, desc="Cover", data=cover))
    id3.update_to_v23()
    mp3.save(v2_version=3, v1=1)


def _vorbis_set(vc, tags: Tags) -> None:
    mapping = {
        "title": tags.title, "artist": tags.artist, "album": tags.album, "albumartist": tags.album_artist,
        "date": tags.year, "tracknumber": tags.track, "genre": tags.genre,
    }
    for key, value in mapping.items():
        if key in vc:
            del vc[key]
        if value:
            vc[key] = [value]


def _picture(cover: bytes, mime: str) -> Picture:
    pic = Picture()
    pic.type = 3
    pic.mime = mime
    pic.desc = "Cover"
    pic.data = cover
    try:
        from PIL import Image

        with Image.open(io.BytesIO(cover)) as im:
            pic.width, pic.height = im.size
            pic.depth = 24 if im.mode in ("RGB", "YCbCr") else 32 if im.mode == "RGBA" else 8
    except Exception:
        pass
    return pic


def _write_flac(flac: FLAC, tags: Tags, cover: bytes | None, mime: str) -> None:
    if flac.tags is None:
        flac.add_tags()
    _vorbis_set(flac.tags, tags)
    if cover is not None:
        flac.clear_pictures()
        flac.add_picture(_picture(cover, mime))
    flac.save()


def _write_ogg(ogg: OggVorbis, tags: Tags, cover: bytes | None, mime: str) -> None:
    if ogg.tags is None:
        ogg.add_tags()
    _vorbis_set(ogg.tags, tags)
    if cover is not None:
        if "metadata_block_picture" in ogg.tags:
            del ogg.tags["metadata_block_picture"]
        ogg.tags["metadata_block_picture"] = [base64.b64encode(_picture(cover, mime).write()).decode("ascii")]
    ogg.save()


def _write_mp4(mp4: MP4, tags: Tags, cover: bytes | None, mime: str) -> None:
    if mp4.tags is None:
        mp4.add_tags()
    mapping = {
        "\xa9nam": tags.title, "\xa9ART": tags.artist, "\xa9alb": tags.album, "aART": tags.album_artist,
        "\xa9day": tags.year, "\xa9gen": tags.genre,
    }
    for key, value in mapping.items():
        if key in mp4.tags:
            del mp4.tags[key]
        if value:
            mp4.tags[key] = [value]
    if "trkn" in mp4.tags:
        del mp4.tags["trkn"]
    n, total = parse_track(tags.track)
    if n:
        mp4.tags["trkn"] = [(n, total)]
    if cover is not None:
        fmt = MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG
        mp4.tags["covr"] = [MP4Cover(cover, imageformat=fmt)]
    mp4.save()


def parse_track(text: str) -> tuple[int, int]:
    m = re.match(r"\s*(\d+)\s*(?:/\s*(\d+))?", text or "")
    if not m:
        return 0, 0
    return int(m.group(1)), int(m.group(2) or 0)


# ------------------------------------------------------------------ cover
def prepare_cover(data: bytes, max_px: int = COVER_MAX_PX_DEFAULT, quality: int = COVER_JPEG_QUALITY) -> tuple[bytes, str]:
    """JPEG no larger than max_px on the long side. Small JPEGs pass through untouched."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as im:
        im.load()
        is_jpeg = (im.format or "").upper() == "JPEG"
        if is_jpeg and max(im.size) <= max_px and len(data) <= COVER_KEEP_LIMIT:
            return data, "image/jpeg"
        out = im.convert("RGB")
        if max(out.size) > max_px:
            out.thumbnail((max_px, max_px), Image.LANCZOS)
        buf = io.BytesIO()
        out.save(buf, "JPEG", quality=quality, optimize=True)
        return buf.getvalue(), "image/jpeg"


# ------------------------------------------------------------------ rename
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename(text: str) -> str:
    text = _BAD_CHARS.sub("_", text).strip(" .")
    return text[:120] if text else ""


def rename_target(path: str, tags: Tags) -> str | None:
    """'Artist - Title.ext' beside the file, or None when the tags do not allow one."""
    if not tags.title:
        return None
    stem = safe_filename(f"{tags.artist} - {tags.title}" if tags.artist else tags.title)
    if not stem:
        return None
    folder, name = os.path.split(path)
    ext = os.path.splitext(name)[1]
    if os.path.normcase(stem + ext) == os.path.normcase(name):
        return None
    target = os.path.join(folder, stem + ext)
    n = 2
    while os.path.exists(target):
        target = os.path.join(folder, f"{stem} ({n}){ext}")
        n += 1
    return target


def rename_file(path: str, target: str) -> str:
    try:
        os.replace(path, target)
    except OSError as exc:
        raise FileLocked(path) from exc
    old_backup = backup_path(path)
    if os.path.exists(old_backup):
        try:
            os.replace(old_backup, backup_path(target))
        except OSError:
            pass
    return target


# ------------------------------------------------------------------ backup / undo
def backup_path(path: str) -> str:
    return path + BACKUP_SUFFIX


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_backup(path: str, overwrite: bool = False) -> str:
    """Write <file>.tagbak.json unless it already exists (the first backup is the original)."""
    target = backup_path(path)
    if os.path.exists(target) and not overwrite:
        return target
    fmt = format_of(path)
    if fmt is None:
        raise UnsupportedFile(path)
    info = read_file(path)
    with open(path, "rb") as f:
        raw = f.read()
    record = {
        "version": BACKUP_VERSION,
        "file": os.path.basename(path),
        "format": fmt,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "size": len(raw),
        "sha256": sha256_bytes(raw),
        "tags": info.tags.as_dict(),
        "cover": {"mime": info.cover_mime, "b64": base64.b64encode(info.cover).decode("ascii")} if info.cover else None,
        "layout": None,
    }
    try:
        head_end, tail_start, extra = _layout(raw, fmt)
        # ID3 padding and duplicate pictures make the head region up to a few MB;
        # zlib shrinks the padding to nothing, so the backup stays near cover size.
        record["layout"] = {
            "head_z": base64.b64encode(zlib.compress(raw[:head_end], 6)).decode("ascii"),
            "tail_z": base64.b64encode(zlib.compress(raw[tail_start:], 6)).decode("ascii"),
            "audio_len": tail_start - head_end,
            **extra,
        }
    except (ValueError, struct.error):
        pass  # undo will fall back to tag values
    tmp = target + ".part"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False)
        os.replace(tmp, target)
    except OSError as exc:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise FileLocked(target) from exc
    return target


def load_backup(path: str) -> dict:
    target = backup_path(path)
    try:
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        raise NoBackup(target) from exc
    if not isinstance(data, dict) or not isinstance(data.get("tags"), dict):
        raise NoBackup(target)
    return data


def restore_backup(path: str) -> bool:
    """Put the original tags back. Returns True when the file is byte-identical
    to the original, False when only the tag values could be restored."""
    record = load_backup(path)
    fmt = format_of(path)
    layout = record.get("layout")
    if fmt and isinstance(layout, dict) and fmt == record.get("format"):
        try:
            with open(path, "rb") as f:
                current = f.read()
            audio = _audio_bytes(current, fmt, layout)
            if audio is not None and len(audio) == layout.get("audio_len"):
                rebuilt = _layout_bytes(layout, "head") + audio + _layout_bytes(layout, "tail")
                if sha256_bytes(rebuilt) == record.get("sha256"):
                    _atomic_write(path, rebuilt)
                    return True
        except (OSError, ValueError, struct.error, KeyError) as exc:
            if isinstance(exc, PermissionError):
                raise FileLocked(path) from exc
    cover = record.get("cover")
    data = base64.b64decode(cover["b64"]) if isinstance(cover, dict) and cover.get("b64") else None
    mime = str(cover.get("mime") or "image/jpeg") if isinstance(cover, dict) else "image/jpeg"
    write_file(path, Tags.from_dict(record["tags"]), data, mime)
    if data is None:
        _remove_cover(path)
    return False


def _layout_bytes(layout: dict, part: str) -> bytes:
    """Backups written before compression hold `<part>_b64`; newer ones `<part>_z`."""
    if f"{part}_z" in layout:
        return zlib.decompress(base64.b64decode(layout[f"{part}_z"]))
    return base64.b64decode(layout[f"{part}_b64"])


def _remove_cover(path: str) -> None:
    fmt, audio = _open(path)
    if fmt == "MP3" and audio.tags is not None:
        audio.tags.delall("APIC")
        audio.save(v2_version=3, v1=1)
    elif fmt == "FLAC":
        audio.clear_pictures()
        audio.save()
    elif fmt == "M4A" and audio.tags is not None and "covr" in audio.tags:
        del audio.tags["covr"]
        audio.save()
    elif fmt == "OGG" and audio.tags is not None and "metadata_block_picture" in audio.tags:
        del audio.tags["metadata_block_picture"]
        audio.save()


def _atomic_write(path: str, data: bytes) -> None:
    tmp = path + ".part"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except OSError as exc:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise FileLocked(path) from exc


# ------------------------------------------------------------------ byte layout
def _layout(raw: bytes, fmt: str) -> tuple[int, int, dict]:
    """(head_end, tail_start, extra): the audio region is raw[head_end:tail_start]
    and is the part mutagen never rewrites."""
    if fmt == "MP3":
        head = _skip_id3v2(raw, 0)
        tail = len(raw) - 128 if len(raw) >= 128 and raw[-128:-125] == b"TAG" else len(raw)
        return head, max(head, tail), {}
    if fmt == "FLAC":
        pos = _skip_id3v2(raw, 0)
        if raw[pos:pos + 4] != b"fLaC":
            raise ValueError("no fLaC marker")
        pos += 4
        while True:
            if pos + 4 > len(raw):
                raise ValueError("truncated metadata")
            flag = raw[pos]
            size = int.from_bytes(raw[pos + 1:pos + 4], "big")
            pos += 4 + size
            if flag & 0x80:
                break
        return pos, len(raw), {}
    if fmt == "M4A":
        atoms = _top_atoms(raw)
        mdats = [a for a in atoms if a[0] == b"mdat"]
        if len(mdats) != 1:
            raise ValueError("need exactly one mdat")
        _, start, header_len, end = mdats[0]
        return start + header_len, end, {}
    if fmt == "OGG":
        head_end, next_seq = _ogg_header_end(raw)
        return head_end, len(raw), {"ogg_first_seq": next_seq}
    raise ValueError(fmt)


def _audio_bytes(current: bytes, fmt: str, layout: dict) -> bytes | None:
    head_end, tail_start, _ = _layout(current, fmt)
    audio = current[head_end:tail_start]
    if fmt != "OGG":
        return audio
    # mutagen renumbers the pages after the headers when the header page count
    # changes; put the original sequence numbers back so the bytes match again.
    seq = int(layout.get("ogg_first_seq", 0))
    fileobj = io.BytesIO(audio)
    out = io.BytesIO()
    while True:
        try:
            page = OggPage(fileobj)
        except EOFError:
            break
        page.sequence = seq
        seq += 1
        out.write(page.write())
    return out.getvalue()


def _skip_id3v2(raw: bytes, pos: int) -> int:
    while raw[pos:pos + 3] == b"ID3" and len(raw) >= pos + 10:
        flags = raw[pos + 5]
        size = _syncsafe(raw[pos + 6:pos + 10])
        pos += 10 + size + (10 if flags & 0x10 else 0)
    return pos


def _syncsafe(b: bytes) -> int:
    return (b[0] << 21) | (b[1] << 14) | (b[2] << 7) | b[3]


def _top_atoms(raw: bytes) -> list[tuple[bytes, int, int, int]]:
    """[(type, offset, header_len, end)] for the top-level MP4 atoms."""
    atoms = []
    pos = 0
    n = len(raw)
    while pos + 8 <= n:
        size = struct.unpack(">I", raw[pos:pos + 4])[0]
        kind = raw[pos + 4:pos + 8]
        header = 8
        if size == 1:
            if pos + 16 > n:
                raise ValueError("truncated atom")
            size = struct.unpack(">Q", raw[pos + 8:pos + 16])[0]
            header = 16
        elif size == 0:
            size = n - pos
        if size < header or pos + size > n:
            raise ValueError("bad atom size")
        atoms.append((kind, pos, header, pos + size))
        pos += size
    if pos != n:
        raise ValueError("trailing bytes")
    return atoms


def _ogg_header_end(raw: bytes) -> tuple[int, int]:
    """Offset after the pages holding the three Vorbis header packets, and the
    sequence number of the first audio page."""
    fileobj = io.BytesIO(raw)
    completed = 0
    serial = None
    while completed < 3:
        try:
            page = OggPage(fileobj)
        except EOFError as exc:
            raise ValueError("no vorbis headers") from exc
        if serial is None:
            serial = page.serial
        if page.serial != serial:
            raise ValueError("multiplexed ogg")
        completed += len(page.packets) - (0 if page.complete else 1)
        last = page
    return fileobj.tell(), last.sequence + 1
