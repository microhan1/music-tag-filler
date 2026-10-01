# 音楽タグ補完 (Music Tag Filler)

<img src="assets/icon.png" width="96" alt="icon">

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

**ジャケットの一括登録**：アルバムフォルダのように複数のファイルを入れると、ジャケットのプレビューの下に**このジャケットを全曲に**ボタンが表示されます。

1. ジャケットのあるファイルを選びます。候補の適用、**ジャケット画像を選ぶ**、画像をジャケット欄にドロップして入れたものでも構いません。
2. **このジャケットを全曲に**を押して確認すると、一覧の他のファイルすべてに同じジャケットが入ります。
3. **すべて保存**を押すとファイルに書き込まれます。元に戻すはファイルごとにそのまま使えます。

```bash
python main.py song.mp3                      # 番号付きの候補を表示して選ばせる
python main.py music_folder --auto --rename  # 一致度 90 以上なら確認せず保存し、改名も行う
python main.py song.mp3 --undo               # バックアップから元のタグに戻す
```

`python main.py --help` は OS の言語（한국어 · English · 中文 · 日本語）でオプションを表示します。

exe も同じ引数を受け付けます（`music-tag-filler.exe song.mp3 --auto`）。ただしウィンドウモードでビルドしているため、環境によってはコンソールに出力が表示されません。その場合は出力をファイルに向けるか（`> log.txt`）、ソースから実行してください。引数があっても出力先のコンソールが無いときは、そのファイルを読み込んだ画面が開きます。

テストは `pip install -r requirements-dev.txt` の後 `python -m pytest tests` で実行します。フィクスチャは `samples/` の音源を使います。

## アーティスト識別子

同じ歌手が `岡田 有希子`、`岡田有希子`、`Yukiko Okada` のように別々の表記で保存されていても後で同一人物としてまとめられるよう、保存時に名前とは別に識別子をタグへ書き込みます。タグ名は MusicBrainz Picard と同じなので他のツールでも読めます。

| 内容 | mp3 | flac · ogg | m4a |
| --- | --- | --- | --- |
| MusicBrainz アーティスト ID | `TXXX:MusicBrainz Artist Id` | `MUSICBRAINZ_ARTISTID` | `MusicBrainz Artist Id` |
| アルバムアーティスト ID | `TXXX:MusicBrainz Album Artist Id` | `MUSICBRAINZ_ALBUMARTISTID` | `MusicBrainz Album Artist Id` |
| アルバム（リリース）ID | `TXXX:MusicBrainz Album Id` | `MUSICBRAINZ_ALBUMID` | `MusicBrainz Album Id` |
| 録音 ID | `UFID:http://musicbrainz.org` | `MUSICBRAINZ_TRACKID` | `MusicBrainz Track Id` |
| ソート名（例: `Okada, Yukiko`） | `TSOP`、`TSO2` | `ARTISTSORT`、`ALBUMARTISTSORT` | `soar`、`soaa` |
| iTunes アーティスト ID | `TXXX:iTunes Artist Id` | `ITUNES_ARTISTID` | `iTunes Artist Id` |

- MusicBrainz の候補を適用すると MusicBrainz ID とソート名を、iTunes の候補なら iTunes アーティスト ID を書き込みます。統合された候補は両方を書き込みます。
- アーティストが複数いる場合は ID も複数書き込みます（mp3 は `/` でつなぎます）。自動選択されたファイルにも書き込みます。
- 入力欄の下の「識別子」行で、そのファイルにどの識別子があるかを確認できます。元に戻すと識別子も元に戻ります。
- 表示用のアーティスト名は選んだ候補の原文です。`settings.json` の `artist_name_preference` を `"latin"` にすると、MusicBrainz がラテン文字の名前を明確に示す場合に限りその名前を使います（既定は `"original"`）。

## タグを埋めたら：フォルダ整理

タグを埋めたら、[音楽フォルダ整理 (music-folder-organizer)](https://github.com/microhan1/music-folder-organizer) で `アーティスト/アルバム/01 - タイトル.mp3` の構成に移し、重複も整理できます。インターネット接続は不要で、実行前にプレビューを表示し、毎回の整理を元に戻せます。

- ここで書き込んだ MusicBrainz アーティスト ID で `岡田 有希子`・`岡田有希子` のような表記の違いを一つのフォルダにまとめ、ソート名は整理ルールの `{artist_sort}` で使えます。
- このツールのバックアップ `<ファイル名>.tagbak.json` も音楽ファイルと一緒に移動するので、フォルダ整理の後もここで **元に戻す** が使えます。

## 音で探すための準備

- `third_party/fpcalc.exe`（Chromaprint）が必要です。リポジトリに同梱しています。無い場合は [Chromaprint Releases](https://github.com/acoustid/chromaprint/releases) から `chromaprint-fpcalc-*-windows-x86_64.zip` を取得し、`fpcalc.exe` を `third_party/` に置くか、`settings.json` の `fpcalc_path` にパスを書きます。
- Releases の exe には AcoustID アプリケーションキーが入っているのでそのまま使えます。ソースから実行する場合は [acoustid.org/new-application](https://acoustid.org/new-application) で無料取得したキーを `settings.json` の `acoustid_key` に書くか、1 行の `acoustid_key.txt`（リポジトリには入らない）に置くと build.bat が exe に同梱します。

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
