# 음악 정보 채우기 (Music Tag Filler)

<img src="assets/icon.png" width="96" alt="icon">

[English](README.en.md) · [中文](README.zh-CN.md) · [日本語](README.ja.md)

> **파일은 인터넷으로 올라가지 않습니다.** 검색어와 음향 지문(숫자 열)만 보냅니다.

제목·가수·앨범·표지가 비어 있는 mp3·flac·m4a·ogg를 끌어다 놓으면, 위쪽에 파일에 든 정보를, 아래쪽에 iTunes·MusicBrainz·AcoustID에서 찾은 후보를 보여 주고, 고른 후보를 파일에 써 넣습니다. 서버 없음, 설치 없음, 저장 전에는 파일을 건드리지 않음.

![위·아래 두 파트 화면](docs/screenshot.png)

## 다운로드

- **실행 파일**: [Releases](https://github.com/microhan1/music-tag-filler/releases)에서 `music-tag-filler.exe`를 받아 더블클릭. 설치 없이 바로 실행됩니다. (서명되지 않은 exe라 SmartScreen 경고가 뜨면 "추가 정보 → 실행")
- **소스 실행**:

```bash
pip install -r requirements.txt
python main.py
```

## 사용법

1. 음악 파일이나 폴더를 창에 끌어다 놓습니다. 파일명에서 `가수 - 제목`을 읽어 검색이 바로 돌아갑니다.
2. 아래 표에서 후보를 고르고 **선택 적용**(또는 더블클릭)을 누릅니다. 바뀐 칸은 노란색으로 표시되고, 직접 고칠 수도 있습니다.
3. **저장**을 누릅니다. 원래 태그는 `<파일명>.tagbak.json`에 남고, **되돌리기**로 바이트 단위까지 원래대로 복구됩니다.

여러 파일을 넣으면 파일마다 검색을 돌려 일치도 90 이상인 첫 후보를 자동 선택(회색 체크)해 두고, 목록을 넘기며 확인한 뒤 **전체 저장**을 누르면 됩니다. 제목·가수가 전혀 없는 `track01.mp3` 같은 파일은 **소리로 찾기**를 누르세요.

**표지 일괄 등록**: 앨범 폴더처럼 여러 파일을 넣으면 표지 미리보기 아래에 **이 표지를 목록 전체에** 버튼이 나타납니다.

1. 표지가 있는 파일을 고릅니다. 후보를 적용하거나, **표지 파일 고르기**로 고르거나, 이미지를 표지 칸에 끌어다 놓아 넣은 표지도 됩니다.
2. **이 표지를 목록 전체에**를 누르고 확인하면 목록의 다른 파일 전부에 같은 표지가 들어갑니다.
3. **전체 저장**을 눌러야 파일에 기록됩니다. 되돌리기는 파일마다 그대로 됩니다.

```bash
python main.py song.mp3                      # 후보를 번호로 보여 주고 고르게 함
python main.py music_folder --auto --rename  # 일치도 90 이상이면 묻지 않고 저장 + 파일명 변경
python main.py music_folder --auto --lyrics  # 가사가 없는 파일에는 가사도 넣기
python main.py song.mp3 --undo               # 백업에서 원래 태그로 되돌리기
```

`python main.py --help`가 OS 언어(한국어 · English · 中文 · 日本語)로 옵션을 보여 줍니다.

exe도 같은 인자를 받습니다(`music-tag-filler.exe song.mp3 --auto`). 다만 창 모드로 빌드되어 콘솔에 직접 출력이 안 보이는 환경이 있으니, 그럴 때는 출력을 파일로 보내거나(`> log.txt`) 소스로 실행하세요. 인자가 있어도 출력할 콘솔이 없으면 그 파일을 담은 창이 열립니다.

시험은 `pip install -r requirements-dev.txt` 후 `python -m pytest tests`로 돌립니다. 픽스처는 `samples/`의 음원을 씁니다.

## 가사 채우기

아래 옵션 줄의 **가사도 채우기**를 켜면, 저장할 때 가사가 없는 파일에 가사를 넣습니다. 기본은 꺼져 있습니다. 처음 켤 때와 옆의 **!** 버튼을 누를 때 주의 사항이 나옵니다.

- 가사는 [LRCLIB](https://lrclib.net/)에서 가져옵니다. 사용자들이 올린 무료 가사 모음이며, 곡 제목·아티스트·길이만 보냅니다.
- 이미 가사가 있는 파일은 건드리지 않습니다. 가사만 찾으려던 파일에서 가사를 못 찾으면 파일에 아무것도 쓰지 않습니다.
- 가사 칸에 `[COWON S9]`·`[3 LINES]` 같은 플레이어 표시만 있으면 빈 칸으로 보고 채웁니다. 화면에는 "가사 대신 다른 표시만 있음 · 빈 칸으로 봄"으로 나오고, 되돌리기로 원래 표시가 돌아옵니다. 가사를 못 찾으면 표시는 그대로 둡니다.
- 틀린 가사보다 빈 가사가 낫다는 원칙으로, 다음이 모두 맞을 때만 넣습니다.
  - 아티스트가 같음. 제목만 같은 다른 가수의 곡은 쓰지 않습니다.
  - 버전이 같음. `Instrumental`·`Off Vocal`·`Karaoke`나 `TV size` 표시가 양쪽에서 같아야 합니다. 반주 파일은 찾지도 않습니다.
  - 길이 차이가 3초 이내이고, 시간 표시가 있는 가사라면 곡 끝을 넘지 않음.
  - 같은 곡으로 올라온 가사끼리 내용이 일치함. 같은 글을 여러 번 올린 것은 한 건으로 셉니다. 내용이 갈리면 넣지 않습니다.
  - 일본어 원문 기록과 그 로마자 표기 기록이 함께 있으면 원문을 씁니다. 로마자 기록밖에 없으면 로마자 가사가 들어갑니다.
  - 기록이 하나뿐이고 시간 표시도 없어 대조할 것이 없으면, 곡 길이에 비해 가사가 지나치게 길 때(초당 12글자 초과) 넣지 않습니다. 87초짜리 인트로에 다른 노래의 가사 전체가 올라온 경우가 있었습니다.
- 시간 표시가 없는 일반 가사만 넣습니다.
- LRCLIB에 "가사 없는 곡"으로 표시된 기록만 있으면 넣지 않고 그렇게 알립니다. 가사가 있는 곡인데도 그렇게 표시된 경우가 있어 "반주"라고 부르지 않습니다.
- 파일 정보 아래 **가사:** 줄에 결과가 나옵니다. 가사가 있으면 **가사 보기**로 내용을 볼 수 있습니다.
- LRCLIB 서버는 자주 바쁩니다. 그때는 잠깐 기다려 다시 묻고, 그래도 안 되면 태그만 저장하고 "서버가 바빠 찾지 못함"으로 남깁니다. 다시 저장하면 다시 찾습니다. 5곡 연속 실패하면 그 저장에서는 가사 찾기를 멈춥니다.
- 되돌리기는 가사를 넣기 전 파일로 돌아갑니다.
- 가사에는 저작권이 있습니다. 개인 소장 파일에만 쓰고, 가사가 든 파일을 공유하지 마세요.

| 형식 | 가사 태그 |
| --- | --- |
| mp3 | `USLT` (언어 `und`) |
| flac · ogg | `LYRICS` (읽을 때는 다른 프로그램이 쓰는 `UNSYNCEDLYRICS`도 가사로 봄) |
| m4a | `©lyr` |

## 아티스트 식별 정보

같은 가수가 `岡田 有希子`, `岡田有希子`, `Yukiko Okada`처럼 여러 표기로 저장되어도 나중에 같은 사람으로 묶을 수 있게, 저장할 때 이름 글자와 함께 식별자를 태그에 적습니다. 태그 이름은 MusicBrainz Picard와 같아 다른 도구에서도 읽힙니다.

| 내용 | mp3 | flac · ogg | m4a |
| --- | --- | --- | --- |
| MusicBrainz 아티스트 ID | `TXXX:MusicBrainz Artist Id` | `MUSICBRAINZ_ARTISTID` | `MusicBrainz Artist Id` |
| 앨범 아티스트 ID | `TXXX:MusicBrainz Album Artist Id` | `MUSICBRAINZ_ALBUMARTISTID` | `MusicBrainz Album Artist Id` |
| 앨범(발매) ID | `TXXX:MusicBrainz Album Id` | `MUSICBRAINZ_ALBUMID` | `MusicBrainz Album Id` |
| 녹음 ID | `UFID:http://musicbrainz.org` | `MUSICBRAINZ_TRACKID` | `MusicBrainz Track Id` |
| 정렬용 이름 (예: `Okada, Yukiko`) | `TSOP`, `TSO2` | `ARTISTSORT`, `ALBUMARTISTSORT` | `soar`, `soaa` |
| iTunes 아티스트 ID | `TXXX:iTunes Artist Id` | `ITUNES_ARTISTID` | `iTunes Artist Id` |

- MusicBrainz 후보를 적용하면 MusicBrainz ID와 정렬용 이름을, iTunes 후보를 적용하면 iTunes 아티스트 ID를 적습니다. 두 출처가 합쳐진 후보는 둘 다 적습니다.
- 가수가 여러 명이면 ID도 여러 개 적습니다(mp3는 `/`로 이어 씀). 자동 선택된 파일에도 적습니다.
- 위쪽 칸 아래의 "식별자" 줄에서 그 파일에 어떤 식별자가 있는지 볼 수 있습니다. 되돌리기는 식별자까지 원래대로 돌립니다.
- 표시용 가수명은 고른 후보의 원문 그대로 씁니다. `settings.json`의 `artist_name_preference`를 `"latin"`으로 바꾸면, MusicBrainz가 로마자 이름을 명확히 줄 때에 한해 그 이름을 씁니다(기본 `"original"`).

## 태그를 채운 다음: 폴더 정리

태그를 채웠으면 [음악 폴더 정리 (music-folder-organizer)](https://github.com/microhan1/music-folder-organizer)로 `가수/앨범/01 - 제목.mp3` 구조로 옮기고 중복을 정리할 수 있습니다. 인터넷 없이 동작하고, 실행 전에 미리보기를 보여 주며, 되돌리기가 있습니다.

- 여기서 적은 MusicBrainz·iTunes 아티스트 ID로 `岡田 有希子`·`岡田有希子` 같은 표기 차이를 한 폴더로 묶고(음악 폴더 정리 v0.1.2 이상), 정렬용 이름은 `{artist_sort}`로 폴더 이름에 쓸 수 있습니다.
- 이 도구의 백업 `<파일명>.tagbak.json`도 음악 파일을 따라 함께 옮겨지므로, 폴더를 정리한 뒤에도 여기서 **되돌리기**가 됩니다.

## 소리로 찾기 준비

- `third_party/fpcalc.exe`(Chromaprint)가 필요합니다. 저장소에 동봉되어 있고, 없으면 [Chromaprint Releases](https://github.com/acoustid/chromaprint/releases)에서 `chromaprint-fpcalc-*-windows-x86_64.zip`을 받아 `fpcalc.exe`를 `third_party/`에 넣거나 `settings.json`의 `fpcalc_path`에 경로를 적습니다.
- Releases의 exe에는 AcoustID 애플리케이션 키가 들어 있어 바로 됩니다. 소스로 실행할 때는 [acoustid.org/new-application](https://acoustid.org/new-application)에서 무료로 키를 발급받아 `settings.json`의 `acoustid_key`에 적거나, `acoustid_key.txt`(저장소에 올라가지 않음)에 한 줄로 넣어 두면 build.bat이 exe에 함께 넣습니다.

## 정보 출처

| 출처 | 용도 | 약관 |
| --- | --- | --- |
| [iTunes Search API](https://performance-partners.apple.com/search-api) | 곡·앨범·표지 | [Apple Media Services 이용 약관](https://www.apple.com/legal/internet-services/itunes/) |
| [MusicBrainz](https://musicbrainz.org/) | 곡·앨범·발매 정보 | [MusicBrainz API 이용 규칙](https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting) |
| [AcoustID](https://acoustid.org/) | 음향 지문 → 녹음 ID | [AcoustID 서비스 약관](https://acoustid.org/webservice) |
| [Cover Art Archive](https://coverartarchive.org/) | 앨범 표지 | [CAA 소개](https://musicbrainz.org/doc/Cover_Art_Archive) |
| [LRCLIB](https://lrclib.net/) | 가사 (옵션을 켰을 때만) | [API 문서](https://lrclib.net/docs) |

iTunes 한국 스토어에는 음원 판매가 없어 검색 결과가 비므로, 지정한 국가에서 결과가 없으면 미국 스토어로 자동 폴백합니다. 검색 결과의 곡명·가수명은 출처가 준 원문 그대로 보여 줍니다.

## 하지 않는 것

- 음악 파일을 어디에도 올리지 않습니다. 검색어와 음향 지문(숫자 열)만 보냅니다.
- 가사는 옵션을 켰을 때만 가져오고, 이미 있는 가사는 바꾸지 않습니다. `.lrc` 파일은 만들지 않습니다(필요하면 [LRCGET](https://github.com/tranxuanthang/lrcget)).
- 음원 다운로드·변환·재생 기능은 없습니다.
- 스트리밍 서비스 계정 연동은 없습니다.
- 공식 API가 없는 국내 서비스(멜론·벅스·지니 등)는 긁지 않습니다.
- 사용자가 저장을 누르기 전에는 파일을 건드리지 않습니다.

## MusicBrainz Picard와의 차이

- 설정 없이 "끌어다 놓고, 고르고, 저장" 세 단계로 끝납니다.
- iTunes 검색을 함께 써서 가요·J-POP·중화권 음악과 표지에 강합니다.
- 한국어 UI가 기본이고 영어·중국어·일본어로 바로 바꿀 수 있습니다.

## 라이선스

MIT. [LICENSE](LICENSE) 참조.
동봉된 `third_party/fpcalc.exe`(Chromaprint)는 LGPL-2.1이며 원문은 [third_party/LICENSE-chromaprint](third_party/LICENSE-chromaprint)에 있습니다.
