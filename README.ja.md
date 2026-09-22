# 音楽タグ補完 (Music Tag Filler)

[한국어](README.md) · [English](README.en.md) · [中文](README.zh-CN.md)

> **ファイルはインターネットに送信されません。** 検索語と音声指紋（数字の列）だけを送ります。

タイトル・アーティスト・アルバム・ジャケットが空の mp3 / flac / m4a / ogg をドロップすると、上段にファイル内の情報、下段に iTunes・MusicBrainz・AcoustID で見つかった候補を表示し、選んだ候補をファイルに書き込みます。サーバーなし、インストールなし、保存を押すまでファイルには触れません。

![上下二段の画面](docs/screenshot.png)

## ダウンロード

- **実行ファイル**: [Releases](https://github.com/microhan1/music-tag-filler/releases) から `music-tag-filler.exe` を取得してダブルクリック。インストール不要です。（署名なしのため SmartScreen が警告する場合は「詳細情報 → 実行」）
- **ソースから実行**:

```bash
pip install -r requirements.txt
python main.py
```

## 使い方

1. 音楽ファイルまたはフォルダをウィンドウにドロップします。ファイル名から `アーティスト - タイトル` を読み取り、すぐに検索が始まります。
2. 下の表で候補を選び、**選択を適用**（またはダブルクリック）を押します。変わった欄は黄色になり、手で直すこともできます。
3. **保存**を押します。元のタグは `<ファイル名>.tagbak.json` に残り、**元に戻す**でバイト単位まで復元できます。

複数ファイルを入れると各ファイルを検索し、一致度 90 以上の先頭候補を自動選択（灰色チェック）します。一覧を確認してから**すべて保存**を押してください。`track01.mp3` のような名前のファイルは**音で探す**を押します。

```bash
python main.py song.mp3                      # 番号付きの候補を表示して選ばせる
python main.py music_folder --auto --rename  # 一致度 90 以上なら確認せず保存し、改名も行う
python main.py song.mp3 --undo               # バックアップから元のタグに戻す
```

`python main.py --help` は OS の言語（한국어 · English · 中文 · 日本語）でオプションを表示します。

## 音で探すための準備

- `third_party/fpcalc.exe`（Chromaprint）が必要です。リポジトリに同梱しています。無い場合は [Chromaprint Releases](https://github.com/acoustid/chromaprint/releases) から `chromaprint-fpcalc-*-windows-x86_64.zip` を取得し、`fpcalc.exe` を `third_party/` に置くか、`settings.json` の `fpcalc_path` にパスを書きます。
- AcoustID API キーが必要です。[acoustid.org/new-application](https://acoustid.org/new-application) で無料取得し、`settings.json` の `acoustid_key` に書きます。

## 情報の出典

| 出典 | 用途 | 規約 |
| --- | --- | --- |
| [iTunes Search API](https://performance-partners.apple.com/search-api) | 曲・アルバム・ジャケット | [Apple Media Services 規約](https://www.apple.com/legal/internet-services/itunes/) |
| [MusicBrainz](https://musicbrainz.org/) | 曲・アルバム・リリース情報 | [MusicBrainz API ルール](https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting) |
| [AcoustID](https://acoustid.org/) | 音声指紋 → 録音 ID | [AcoustID サービス規約](https://acoustid.org/webservice) |
| [Cover Art Archive](https://coverartarchive.org/) | アルバムジャケット | [CAA について](https://musicbrainz.org/doc/Cover_Art_Archive) |

iTunes 韓国ストアは音楽を販売していないため結果が常に空になります。指定した国で結果が無いときは自動的に米国ストアを使います。曲名・アーティスト名は出典が返した原文のまま表示します。

## しないこと

- 音楽ファイルをどこにもアップロードしません。検索語と音声指紋だけを送ります。
- 歌詞は取得しません。
- ダウンロード・変換・再生機能はありません。
- ストリーミングサービスのアカウント連携はありません。
- 公式 API のないサービス（Melon・Bugs・Genie など）はスクレイピングしません。
- 保存を押すまでファイルには触れません。

## MusicBrainz Picard との違い

- 設定不要。「ドロップ、選ぶ、保存」の三段階で終わります。
- iTunes 検索を併用し、K-POP・J-POP・中華圏の音楽とジャケットに強いです。
- 韓国語 UI が既定で、英語・中国語・日本語にすぐ切り替えられます。

## ライセンス

MIT。[LICENSE](LICENSE) 参照。
同梱の `third_party/fpcalc.exe`（Chromaprint）は LGPL-2.1 で、原文は [third_party/LICENSE-chromaprint](third_party/LICENSE-chromaprint) にあります。
