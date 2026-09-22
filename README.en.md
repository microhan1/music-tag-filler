# Music Tag Filler (음악 정보 채우기)

[한국어](README.md) · [中文](README.zh-CN.md) · [日本語](README.ja.md)

> **Your files are never uploaded.** Only the search query and an audio fingerprint (a string of numbers) are sent.

Drop mp3 / flac / m4a / ogg files with missing title, artist, album or cover art. The top half shows what the file contains, the bottom half shows candidates from iTunes, MusicBrainz and AcoustID, and the one you pick is written into the file. No server, no install, nothing is touched before you press Save.

![Two-part window](docs/screenshot.png)

## Download

- **Executable**: grab `music-tag-filler.exe` from [Releases](https://github.com/microhan1/music-tag-filler/releases) and double-click it. Nothing to install. (The exe is unsigned; if SmartScreen warns, choose "More info → Run anyway".)
- **Run from source**:

```bash
pip install -r requirements.txt
python main.py
```

## Usage

1. Drop music files or a folder onto the window. `Artist - Title` is read from the file name and the search starts right away.
2. Pick a candidate in the table and press **Apply selected** (or double-click). Changed fields turn yellow; you can edit them by hand.
3. Press **Save**. The original tags are kept in `<file>.tagbak.json`, and **Undo** restores the file byte for byte.

With several files, each one is searched and the first candidate scoring 90 or more is pre-selected (grey check). Step through the list, then press **Save all**. For files with no usable name such as `track01.mp3`, press **Find by sound**.

```bash
python main.py song.mp3                      # lists numbered candidates and asks
python main.py music_folder --auto --rename  # saves without asking at match >= 90, renames too
python main.py song.mp3 --undo               # restores the original tags from the backup
```

`python main.py --help` prints the options in your OS language (한국어 · English · 中文 · 日本語).

## Find by sound setup

- `third_party/fpcalc.exe` (Chromaprint) is bundled in the repository. If missing, download `chromaprint-fpcalc-*-windows-x86_64.zip` from [Chromaprint Releases](https://github.com/acoustid/chromaprint/releases) and put `fpcalc.exe` in `third_party/`, or set `fpcalc_path` in `settings.json`.
- An AcoustID API key is required. Register one for free at [acoustid.org/new-application](https://acoustid.org/new-application) and put it in `acoustid_key` in `settings.json`.

## Data sources

| Source | Used for | Terms |
| --- | --- | --- |
| [iTunes Search API](https://performance-partners.apple.com/search-api) | songs, albums, cover art | [Apple Media Services terms](https://www.apple.com/legal/internet-services/itunes/) |
| [MusicBrainz](https://musicbrainz.org/) | songs, albums, release data | [MusicBrainz API rules](https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting) |
| [AcoustID](https://acoustid.org/) | fingerprint → recording ID | [AcoustID web service terms](https://acoustid.org/webservice) |
| [Cover Art Archive](https://coverartarchive.org/) | album covers | [About the CAA](https://musicbrainz.org/doc/Cover_Art_Archive) |

The Korean iTunes storefront sells no music and returns nothing, so when the chosen country has no results the US store is tried automatically. Titles and artist names are shown exactly as the source returns them.

## What it does not do

- Never uploads a music file anywhere. Only the query and the fingerprint are sent.
- No lyrics.
- No downloading, converting or playing music.
- No streaming-service accounts.
- No scraping of services without an official API (Melon, Bugs, Genie, ...).
- Nothing is written before you press Save.

## Compared with MusicBrainz Picard

- No setup: drop, pick, save.
- iTunes search alongside MusicBrainz makes it strong for K-pop, J-pop, Chinese music and cover art.
- Korean UI by default, switchable to English, Chinese and Japanese.

## License

MIT. See [LICENSE](LICENSE).
The bundled `third_party/fpcalc.exe` (Chromaprint) is LGPL-2.1; the text is in [third_party/LICENSE-chromaprint](third_party/LICENSE-chromaprint).
