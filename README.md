# 음악 정보 채우기 (Music Tag Filler)

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

```bash
python main.py song.mp3                      # 후보를 번호로 보여 주고 고르게 함
python main.py music_folder --auto --rename  # 일치도 90 이상이면 묻지 않고 저장 + 파일명 변경
python main.py song.mp3 --undo               # 백업에서 원래 태그로 되돌리기
```

`python main.py --help`가 OS 언어(한국어 · English · 中文 · 日本語)로 옵션을 보여 줍니다.

## 소리로 찾기 준비

- `third_party/fpcalc.exe`(Chromaprint)가 필요합니다. 저장소에 동봉되어 있고, 없으면 [Chromaprint Releases](https://github.com/acoustid/chromaprint/releases)에서 `chromaprint-fpcalc-*-windows-x86_64.zip`을 받아 `fpcalc.exe`를 `third_party/`에 넣거나 `settings.json`의 `fpcalc_path`에 경로를 적습니다.
- AcoustID API 키가 필요합니다. [acoustid.org/new-application](https://acoustid.org/new-application)에서 무료로 발급받아 `settings.json`의 `acoustid_key`에 적습니다.

## 정보 출처

| 출처 | 용도 | 약관 |
| --- | --- | --- |
| [iTunes Search API](https://performance-partners.apple.com/search-api) | 곡·앨범·표지 | [Apple Media Services 이용 약관](https://www.apple.com/legal/internet-services/itunes/) |
| [MusicBrainz](https://musicbrainz.org/) | 곡·앨범·발매 정보 | [MusicBrainz API 이용 규칙](https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting) |
| [AcoustID](https://acoustid.org/) | 음향 지문 → 녹음 ID | [AcoustID 서비스 약관](https://acoustid.org/webservice) |
| [Cover Art Archive](https://coverartarchive.org/) | 앨범 표지 | [CAA 소개](https://musicbrainz.org/doc/Cover_Art_Archive) |

iTunes 한국 스토어에는 음원 판매가 없어 검색 결과가 비므로, 지정한 국가에서 결과가 없으면 미국 스토어로 자동 폴백합니다. 검색 결과의 곡명·가수명은 출처가 준 원문 그대로 보여 줍니다.

## 하지 않는 것

- 음악 파일을 어디에도 올리지 않습니다. 검색어와 음향 지문(숫자 열)만 보냅니다.
- 가사는 가져오지 않습니다.
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
