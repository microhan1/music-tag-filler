"""Entry point for music-tag-filler.

    python main.py                                   -> GUI
    python main.py song.mp3 [--auto] [--country KR] [--rename]
    python main.py song.mp3 --undo                   -> restore from <song>.tagbak.json
"""
from __future__ import annotations

import argparse
import os
import sys

import i18n
import pipeline
import prefs as prefs_mod
import tags
from i18n import t
from match import AUTO_SELECT_SCORE, Candidate
from search_itunes import COUNTRIES


def _preselect_lang(argv: list[str]) -> str | None:
    """--lang has to be known before the parser is built, so help is translated."""
    for i, a in enumerate(argv):
        if a == "--lang" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--lang="):
            return a.split("=", 1)[1]
    return None


def _localize_argparse() -> None:
    """argparse's own labels go through gettext; route them to lang files."""
    table = {
        "usage: ": t("cli_usage"),
        "positional arguments": t("cli_positional"),
        "options": t("cli_options"),
        "show this help message and exit": t("cli_help"),
    }
    argparse._ = lambda s: table.get(s, s)  # type: ignore[attr-defined]


def build_parser() -> argparse.ArgumentParser:
    _localize_argparse()
    p = argparse.ArgumentParser(prog="music-tag-filler", description=t("cli_desc"))
    p.add_argument("inputs", nargs="*", help=t("cli_inputs"))
    p.add_argument("--auto", action="store_true", help=t("cli_auto", score=AUTO_SELECT_SCORE))
    p.add_argument("--country", choices=COUNTRIES, help=t("cli_country"))
    p.add_argument("--rename", action="store_true", help=t("cli_rename"))
    p.add_argument("--sound", action="store_true", help=t("cli_sound"))
    p.add_argument("--undo", action="store_true", help=t("cli_undo"))
    p.add_argument("--no-recurse", action="store_true", help=t("cli_no_recurse"))
    p.add_argument("--lang", choices=i18n.LANGS, help=t("cli_lang"))
    p.add_argument("--gui", action="store_true", help=t("cli_gui"))
    return p


def _print_candidates(cands: list[Candidate]) -> None:
    for i, c in enumerate(cands, 1):
        length = _fmt_length(c.length)
        print(t("cli_candidate", index=i, score=c.score, title=c.title, artist=c.artist, album=c.album,
                year=c.year, length=length, source=c.source_label()))


def _fmt_length(seconds: float | None) -> str:
    if not seconds:
        return "-"
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def _on_wait(seconds: float) -> None:
    print(t("err_rate_limit", sec=int(round(seconds))), file=sys.stderr)


def _choose(cands: list[Candidate], allow_sound: bool) -> Candidate | str | None:
    """Ask for a number; '' skips, 's' means try the fingerprint search."""
    while True:
        try:
            answer = input(t("cli_prompt_choice", count=len(cands), sound="s" if allow_sound else "")).strip().lower()
        except EOFError:
            return None
        if answer == "":
            return None
        if answer == "s" and allow_sound:
            return "sound"
        if answer.isdigit() and 1 <= int(answer) <= len(cands):
            return cands[int(answer) - 1]


def _apply(info: tags.FileInfo, cand: Candidate) -> tags.Tags:
    values = cand.tag_values()
    merged = info.tags.as_dict()
    for key, value in values.items():
        if value:
            merged[key] = value
    return tags.Tags.from_dict(merged)


def run_undo(files: list[str]) -> int:
    failures = 0
    for path in files:
        name = os.path.basename(path)
        try:
            exact = tags.restore_backup(path)
        except tags.NoBackup:
            print(t("msg_no_backup", name=name))
            failures += 1
            continue
        except tags.FileLocked:
            print(t("err_readonly") + f": {name}", file=sys.stderr)
            failures += 1
            continue
        print(t("msg_restored_exact" if exact else "msg_restored_tags", name=name))
    return 1 if failures else 0


def run_cli(args: argparse.Namespace) -> int:
    missing = [p for p in args.inputs if not os.path.exists(p)]
    for p in missing:
        print(t("err_open_failed", name=p), file=sys.stderr)
    files = tags.collect_files(args.inputs, recurse=not args.no_recurse)
    if not files:
        print(t("cli_no_input"), file=sys.stderr)
        return 2
    if args.undo:
        return 1 if run_undo(files) or missing else 0
    prefs = prefs_mod.load()
    if args.country:
        prefs.country = args.country
    if args.rename:
        prefs.rename = True
    country = prefs.effective_country()
    interactive = sys.stdin.isatty() and not args.auto
    failures, saved = len(missing), 0
    for idx, path in enumerate(files, 1):
        name = os.path.basename(path)
        try:
            info = tags.read_file(path)
        except (tags.UnsupportedFile, OSError):
            print(t("err_open_failed", name=name), file=sys.stderr)
            failures += 1
            continue
        print(t("cli_file_header", index=idx, total=len(files), name=name, fmt=info.fmt,
                length=_fmt_length(info.length), bitrate=info.bitrate))
        print(t("cli_current_tags", title=info.tags.title, artist=info.tags.artist, album=info.tags.album))
        query = pipeline.query_text(info)
        try:
            if args.sound:
                result = pipeline.search_sound(path, prefs, query, info.length, on_wait=_on_wait)
            else:
                print(t("msg_searching") + f" {query}")
                result = pipeline.search_text(query, country, info.length, on_wait=_on_wait)
                if not result.candidates:
                    result = pipeline.search_sound(path, prefs, query, info.length, on_wait=_on_wait)
        except KeyboardInterrupt:
            print("\n" + t("status_cancelled"))
            return 130
        for key in result.errors:
            print(t(key), file=sys.stderr)
        cands = result.candidates
        if not cands:
            print(t("msg_no_results"))
            failures += 1
            continue
        _print_candidates(cands)
        chosen: Candidate | None = None
        if args.auto:
            chosen = pipeline.auto_pick(result)
            if chosen is None:
                print(t("cli_auto_skipped", score=cands[0].score))
        elif interactive:
            pick = _choose(cands, allow_sound=not args.sound)
            if pick == "sound":
                result = pipeline.search_sound(path, prefs, query, info.length, on_wait=_on_wait)
                for key in result.errors:
                    print(t(key), file=sys.stderr)
                if result.candidates:
                    _print_candidates(result.candidates)
                    pick = _choose(result.candidates, allow_sound=False)
                else:
                    print(t("msg_no_results"))
                    pick = None
            chosen = pick if isinstance(pick, Candidate) else None
        else:
            print(t("cli_not_interactive"))
        if chosen is None:
            print(t("log_skipped", name=name))
            continue
        new_tags = _apply(info, chosen)
        cover = pipeline.fetch_cover(chosen, on_wait=_on_wait)
        try:
            res = pipeline.save_file(path, new_tags, cover, prefs)
        except tags.FileLocked:
            print(t("err_readonly") + f": {name}", file=sys.stderr)
            failures += 1
            continue
        print(t("log_saved", path=res.path))
        print(t("msg_backup_note", file=os.path.basename(res.backup)))
        if res.cover_failed or (chosen.cover_url and cover is None):
            print(t("msg_cover_failed"))
        saved += 1
    print(t("msg_saved", count=saved))
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Windows consoles default to cp949; Chinese/Japanese titles would crash print().
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    i18n.init(_preselect_lang(argv))
    args = build_parser().parse_args(argv)
    if args.lang:
        i18n.set_lang(args.lang, persist=False)
    # A windowed exe has no console, so dropping files on it opens the GUI
    # with those files loaded instead of running the CLI into nowhere.
    headless = getattr(sys, "frozen", False) and sys.stdout is None
    if args.gui or headless or not args.inputs:
        import gui

        gui.launch(args.inputs or None)
        return 0
    try:
        return run_cli(args)
    except KeyboardInterrupt:
        print("\n" + t("status_cancelled"))
        return 130


if __name__ == "__main__":
    sys.exit(main())
