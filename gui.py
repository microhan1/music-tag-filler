"""tkinter GUI for music-tag-filler: current file info on top, search
candidates below, action bar at the bottom."""
from __future__ import annotations

import concurrent.futures
import dataclasses
import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from PIL import Image, ImageDraw, ImageTk

import i18n
import net
import pipeline
import prefs as prefs_mod
import tags
from i18n import t
import match
from match import Candidate
import search_itunes
import search_lyrics
import update_check
from search_itunes import COUNTRIES

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    _HAS_DND = True
except Exception:  # pragma: no cover - optional dependency
    _HAS_DND = False

COVER_PX = 240
THUMB_PX = 40
PREVIEW_PX = 320  # hover preview of a candidate's cover
PREVIEW_DELAY_MS = 250
TOP_PANE_PX = 424
LYRICS_BUSY_LIMIT = 5  # this many lookups in a row failing: stop asking LRCLIB for this save
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif")
CHECK = "\u2713"

# palette
BG = "#f3f4f6"
CARD = "#ffffff"
BORDER = "#d1d5db"
TEXT = "#1f2937"
MUTED = "#6b7280"
ACCENT = "#2563eb"
ACCENT_DARK = "#1d4ed8"
STRIPE = "#f9fafb"
CHANGED_BG = "#fef3c7"
NORMAL_BG = CARD
AUTO_FG = "#9ca3af"
DONE_FG = "#15803d"
NOTICE = "#d97706"
UPDATE_BG = "#eff6ff"
UPDATE_BORDER = "#bfdbfe"
UPDATE_SLUG = "musictag"  # the tool's name on the 책갈피 tools site
NOTICE_DARK = "#b45309"
GOOD_FG = "#15803d"
FAIR_FG = "#b45309"
TIP_BG = "#fffbe6"


def _working_set_mb() -> int | None:
    """Resident memory of this process in MB (Windows only; None elsewhere)."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE  # a 64-bit pseudo handle; c_int would truncate it
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return None
        return int(counters.WorkingSetSize // (1024 * 1024))
    except Exception:
        return None


def _enable_dpi_awareness() -> None:
    """Crisp text on high-DPI screens instead of a bitmap-stretched window."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _screen_box(x: int, y: int, widget: tk.Misc) -> tuple[int, int, int, int]:
    """Left, top, right and bottom of the monitor holding (x, y), so a tooltip on a second
    monitor stays there; the main screen when Windows cannot say."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                            ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

            user32 = ctypes.WinDLL("user32")
            user32.MonitorFromPoint.restype = wintypes.HMONITOR
            user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
            user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
            monitor = user32.MonitorFromPoint(wintypes.POINT(x, y), 2)  # MONITOR_DEFAULTTONEAREST
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                r = info.rcMonitor
                if r.right > r.left and r.bottom > r.top:
                    return r.left, r.top, r.right, r.bottom
        except Exception:
            pass
    return 0, 0, widget.winfo_screenwidth(), widget.winfo_screenheight()


class Tooltip:
    """A small note under a widget while the mouse rests on it (standard tkinter only).
    It appears DELAY_MS after the pointer enters and goes when the pointer leaves or clicks.
    The text is read when it is shown and again by refresh(), so switching the language
    changes it even while it is up. It is kept inside the program window and the screen."""

    DELAY_MS = 450

    def __init__(self, widget: tk.Misc, get_text, font, px) -> None:
        self.widget, self.get_text, self.font, self.px = widget, get_text, font, px
        self.tip: tk.Toplevel | None = None
        self.label: tk.Label | None = None
        self._job: str | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")
        widget.bind("<Destroy>", self.hide, add="+")

    def _schedule(self, _event=None) -> None:
        self._cancel()
        self._job = self.widget.after(self.DELAY_MS, self.show)

    def _cancel(self) -> None:
        if self._job is not None:
            try:
                self.widget.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

    def show(self) -> None:
        self._job = None
        if self.tip is not None or not self.widget.winfo_exists() or not self.widget.winfo_viewable():
            return
        p = self.px
        tip = tk.Toplevel(self.widget)
        tip.withdraw()
        tip.overrideredirect(True)
        tip.configure(bg=BORDER)
        # 400 keeps each language on one line (Japanese at 320 left a lone "）" below)
        self.label = tk.Label(tip, text=self.get_text(), font=self.font, justify="left", wraplength=p(400),
                              bg=TIP_BG, fg=TEXT, bd=0, padx=p(8), pady=p(4))
        self.label.pack(padx=1, pady=1)
        self.tip = tip
        self._place()
        tip.deiconify()

    def _place(self) -> None:
        tip, w = self.tip, self.widget
        tip.update_idletasks()
        tw, th = tip.winfo_reqwidth(), tip.winfo_reqheight()
        gap = self.px(4)
        x, y = w.winfo_rootx(), w.winfo_rooty() + w.winfo_height() + gap
        # the button sits at the window's right edge: pull the note inside the window, then the screen
        top = w.winfo_toplevel()
        x = max(top.winfo_rootx(), min(x, top.winfo_rootx() + top.winfo_width() - tw))
        left, upper, right, bottom = _screen_box(w.winfo_rootx(), w.winfo_rooty(), w)
        x = max(left, min(x, right - tw))
        if y + th > bottom:
            y = w.winfo_rooty() - th - gap
        tip.geometry(f"+{x}+{max(upper, y)}")

    def refresh(self) -> None:
        """The current language's text, if the note is up."""
        if self.tip is not None and self.label is not None:
            try:
                self.label.configure(text=self.get_text())
                self._place()
            except tk.TclError:
                pass

    def hide(self, _event=None) -> None:
        self._cancel()
        if self.tip is not None:
            try:
                self.tip.destroy()
            except tk.TclError:
                pass
            self.tip, self.label = None, None


class CoverStore:
    """Downloaded or user-picked covers wait on disk, not in memory, until they
    are saved: a 500-file batch would otherwise hold 100 MB of JPEGs."""

    def __init__(self) -> None:
        self._dir: str | None = None
        self._n = 0

    def put(self, data: bytes) -> str:
        if self._dir is None:
            self._dir = tempfile.mkdtemp(prefix="music-tag-filler-")
        self._n += 1
        path = os.path.join(self._dir, f"cover{self._n}.bin")
        with open(path, "wb") as f:
            f.write(data)
        return path

    @staticmethod
    def get(key: str | None) -> bytes | None:
        if not key:
            return None
        try:
            with open(key, "rb") as f:
                return f.read()
        except OSError:
            return None

    def close(self) -> None:
        if self._dir:
            shutil.rmtree(self._dir, ignore_errors=True)
            self._dir = None


@dataclasses.dataclass
class FileState:
    path: str
    info: tags.FileInfo | None = None
    values: dict[str, str] = dataclasses.field(default_factory=dict)
    has_cover: bool = False  # the file itself carries a cover (bytes are read on demand)
    cover_key: str | None = None  # a new cover waiting in the CoverStore
    cover_changed: bool = False
    pending_ids: tags.Ids | None = None  # identity tags of the applied candidate, written on save
    has_lyrics: bool = False  # the file itself carries real lyrics (the text is read when shown)
    lyrics_lines: int = 0
    lyrics_note: str = ""  # the tag holds only a marker such as "[COWON S9]": treated as empty
    lyrics_status: str = ""  # last lookup this session (search_lyrics.FOUND / NOT_FOUND / BUSY / ...)
    query: str = ""
    candidates: list[Candidate] = dataclasses.field(default_factory=list)
    result: pipeline.SearchResult | None = None
    selected: Candidate | None = None
    auto: bool = False  # picked by the batch, not yet confirmed by the user
    confirmed: bool = False
    saved: bool = False
    error: str | None = None
    searching: bool = False  # a search for this file is queued or running

    def original(self, field: str) -> str:
        return getattr(self.info.tags, field) if self.info else ""

    def changed_fields(self) -> set[str]:
        return {f for f in tags.FIELDS if self.values.get(f, "") != self.original(f)}

    def final_ids(self) -> tags.Ids:
        """Identity tags the file will hold after saving."""
        existing = self.info.ids if self.info else tags.Ids()
        return self.pending_ids.merged_over(existing) if self.pending_ids is not None else existing

    def ids_changed(self) -> bool:
        return self.info is not None and self.pending_ids is not None and self.final_ids() != self.info.ids

    def dirty(self) -> bool:
        return bool(self.changed_fields()) or self.cover_changed or self.ids_changed()

    def lyrics_wanted(self) -> bool:
        """Saving with the lyrics option on would look lyrics up for this file:
        it has none, it can be searched, and no final answer came back this session."""
        return (self.info is not None and not self.has_lyrics and not self.error
                and bool(self.values.get("title", "").strip()) and bool(self.values.get("artist", "").strip())
                and self.lyrics_status not in (search_lyrics.FOUND, search_lyrics.NOT_FOUND, search_lyrics.INSTRUMENTAL,
                                               search_lyrics.CONFLICT, search_lyrics.NO_LYRICS))

    def current_tags(self) -> tags.Tags:
        return tags.Tags.from_dict(self.values)

    def name(self) -> str:
        return os.path.basename(self.path)

    def attach_info(self, info: tags.FileInfo) -> None:
        """Keep the tags, drop the cover bytes: they are re-read when shown or saved."""
        self.has_cover = info.cover is not None
        info.cover = None
        lyrics = info.lyrics or ""
        self.lyrics_note = search_lyrics.marker_only(lyrics)
        self.has_lyrics = bool(lyrics.strip()) and not self.lyrics_note
        self.lyrics_lines = sum(1 for line in lyrics.splitlines() if line.strip())
        info.lyrics = ""
        self.info = info
        self.values = info.tags.as_dict()

    def load_cover(self) -> bytes | None:
        if self.cover_changed:
            return CoverStore.get(self.cover_key)
        if self.has_cover:
            try:
                return tags.read_cover(self.path)[0]
            except Exception:
                return None
        return None


class App:
    def __init__(self, initial_files: list[str] | None = None) -> None:
        _enable_dpi_awareness()
        self.root = TkinterDnD.Tk() if _HAS_DND else tk.Tk()
        self.scale = max(1.0, min(3.0, self.root.winfo_fpixels("1i") / 96.0))
        self.root.geometry(f"{self.px(1140)}x{self.px(820)}")
        self.root.minsize(self.px(960), self.px(700))
        self.root.configure(bg=BG)
        self._set_window_icon()

        self.prefs = prefs_mod.load()
        self.files: list[FileState] = []
        self.current: FileState | None = None
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        # Thumbnails: each URL is fetched once by a persistent pool and cached; a
        # refill of the table only attaches cached images and queues the missing ones.
        self._thumb_pool = concurrent.futures.ThreadPoolExecutor(max_workers=6)
        self._thumbs: dict[str, ImageTk.PhotoImage] = {}
        self._thumb_misses: set[str] = set()  # URLs that returned nothing; not asked again
        self._thumb_inflight: set[str] = set()
        self._thumb_rows: dict[str, str] = {}  # url -> row id in the table shown now
        # hover preview: a borderless window beside the cursor with a larger cover
        self._preview_win: tk.Toplevel | None = None
        self._preview_lbl: tk.Label | None = None
        self._preview_cache: dict[str, ImageTk.PhotoImage] = {}
        self._preview_misses: set[str] = set()
        self._preview_url: str | None = None
        self._preview_job: str | None = None
        self._preview_pos = (0, 0)
        self.covers = CoverStore()
        self._cover_photo: ImageTk.PhotoImage | None = None
        self._placeholder = ImageTk.PhotoImage(self._placeholder_image())
        self._texts: list[tuple[tk.Misc, str, str]] = []
        self._status_key = ""
        self._status_kwargs: dict = {}
        self._closing = False
        self._offline = False
        self._loading_entries = False
        self._loading_shown = False
        self._loading_tick = 0
        self._loading_key = "msg_loading"

        self.var_lang = tk.StringVar(value=i18n.LANG_NAMES[i18n.current_lang()])
        self.var_country = tk.StringVar(value=self.prefs.effective_country())
        # what worker threads read: a plain string kept in step with the combobox on the Tk thread
        self._country = self.var_country.get()
        self.var_rename = tk.BooleanVar(value=self.prefs.rename)
        self.var_save_alert = tk.BooleanVar(value=self.prefs.save_alert)
        self.var_lyrics = tk.BooleanVar(value=self.prefs.lyrics)
        self.var_update_check = tk.BooleanVar(value=self.prefs.update_check)
        self._update_info: update_check.UpdateInfo | None = None
        self._feedback_win: tk.Toplevel | None = None  # the address to copy when no browser opened
        self.var_query = tk.StringVar()
        self.var_fields = {f: tk.StringVar() for f in tags.FIELDS}

        self._style()
        self._build()
        self._apply_texts()
        self._show_file(None)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        threading.Thread(target=self._probe_online, daemon=True).start()
        # once a day, 1.5 s after the window is up, on a background thread; silent on any failure
        update_check.check_async(self.root, UPDATE_SLUG, net.APP_VERSION, self.prefs, self._on_update_result)
        if initial_files:
            self.root.after(100, lambda: self.add_paths(initial_files))

    # ------------------------------------------------------------ look
    def _set_window_icon(self) -> None:
        """assets/icon.ico from the source folder or the PyInstaller bundle."""
        base = os.path.join(i18n.resource_dir(), "assets")
        ico, png = os.path.join(base, "icon.ico"), os.path.join(base, "icon.png")
        try:
            if sys.platform == "win32" and os.path.isfile(ico):
                self.root.iconbitmap(default=ico)  # default= applies to every later window too
            elif os.path.isfile(png):
                self._icon_photo = ImageTk.PhotoImage(Image.open(png))
                self.root.iconphoto(True, self._icon_photo)
        except (tk.TclError, OSError):
            pass  # an icon is cosmetic; never block startup over it

    def px(self, n: int) -> int:
        return int(round(n * self.scale))

    def _placeholder_image(self) -> Image.Image:
        size = self.px(COVER_PX)
        im = Image.new("RGB", (size, size), "#e5e7eb")
        d = ImageDraw.Draw(im)
        # a simple note: two heads, two stems and a beam
        u = size / 12
        d.ellipse((3.2 * u, 7.6 * u, 5.2 * u, 9.0 * u), fill="#c4c9d2")
        d.ellipse((6.6 * u, 6.9 * u, 8.6 * u, 8.3 * u), fill="#c4c9d2")
        d.rectangle((4.9 * u, 3.2 * u, 5.25 * u, 8.3 * u), fill="#c4c9d2")
        d.rectangle((8.3 * u, 2.5 * u, 8.65 * u, 7.6 * u), fill="#c4c9d2")
        d.polygon([(4.9 * u, 3.2 * u), (8.65 * u, 2.5 * u), (8.65 * u, 3.6 * u), (4.9 * u, 4.3 * u)], fill="#c4c9d2")
        return im

    def _style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        base = tkfont.nametofont("TkDefaultFont")
        self.font_body = base.copy()
        self.font_body.configure(size=10)
        self.font_bold = base.copy()
        self.font_bold.configure(size=10, weight="bold")
        self.font_title = base.copy()
        self.font_title.configure(size=16, weight="bold")
        self.font_small = base.copy()
        self.font_small.configure(size=9)
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(name).configure(size=10)
            except tk.TclError:
                pass

        style.configure(".", background=BG, foreground=TEXT, font=self.font_body, bordercolor=BORDER,
                        lightcolor=BG, darkcolor=BG, troughcolor="#e5e7eb", focuscolor=ACCENT)
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=BG)
        style.configure("Card.TLabel", background=CARD)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Title.TLabel", font=self.font_title)
        style.configure("Small.TLabel", font=self.font_small, foreground=MUTED)
        style.configure("TLabelframe", background=BG, borderwidth=1, relief="solid", bordercolor=BORDER)
        style.configure("TLabelframe.Label", background=BG, foreground=MUTED, font=self.font_bold)
        style.configure("TButton", padding=(self.px(12), self.px(6)), background=CARD, bordercolor=BORDER,
                        lightcolor=CARD, darkcolor=CARD)
        style.map("TButton", background=[("active", "#eef2ff"), ("disabled", "#f3f4f6")],
                  foreground=[("disabled", "#9ca3af")])
        style.configure("Accent.TButton", background=ACCENT, foreground="white", bordercolor=ACCENT,
                        lightcolor=ACCENT, darkcolor=ACCENT, font=self.font_bold)
        style.map("Accent.TButton", background=[("active", ACCENT_DARK), ("disabled", "#93c5fd")],
                  foreground=[("disabled", "white")])
        style.configure("Notice.TButton", background=NOTICE, foreground="white", bordercolor=NOTICE,
                        lightcolor=NOTICE, darkcolor=NOTICE, font=self.font_bold, padding=(self.px(6), self.px(2)))
        style.map("Notice.TButton", background=[("active", NOTICE_DARK)], foreground=[("disabled", "white")])
        style.configure("Small.TButton", font=self.font_small, padding=(self.px(8), self.px(1)))
        # 「의견 보내기」: Small.TButton with a blue border while it has the keyboard focus (same size)
        style.configure("Feedback.TButton", font=self.font_small, padding=(self.px(8), self.px(1)))
        style.map("Feedback.TButton", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)],
                  darkcolor=[("focus", ACCENT)])
        style.configure("TCheckbutton", background=BG, indicatorsize=self.px(14), indicatormargin=(0, 0, self.px(6), 0))
        style.map("TCheckbutton", background=[("active", BG)])
        style.configure("TCombobox", fieldbackground=CARD, background=CARD, arrowcolor=MUTED, padding=(4, 2))
        style.map("TCombobox", fieldbackground=[("readonly", CARD)], background=[("readonly", CARD)],
                  foreground=[("readonly", TEXT)], selectbackground=[("readonly", CARD)],
                  selectforeground=[("readonly", TEXT)])
        style.configure("TEntry", fieldbackground=CARD, padding=(self.px(6), self.px(4)))
        style.configure("Treeview", background=CARD, fieldbackground=CARD, rowheight=self.px(THUMB_PX + 8),
                        bordercolor=BORDER, borderwidth=1)
        style.map("Treeview", background=[("selected", "#dbeafe")], foreground=[("selected", TEXT)])
        style.configure("Treeview.Heading", background="#e5e7eb", foreground=TEXT, font=self.font_bold,
                        padding=(self.px(6), self.px(6)), relief="flat")
        style.map("Treeview.Heading", background=[("active", "#d1d5db")])
        style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor="#e5e7eb", bordercolor="#e5e7eb",
                        lightcolor=ACCENT, darkcolor=ACCENT, thickness=self.px(8))
        style.configure("TScrollbar", background="#e5e7eb", troughcolor=BG, bordercolor=BG, arrowcolor=MUTED)
        style.configure("TPanedwindow", background=BG)
        style.configure("Sash", sashthickness=self.px(6), gripcount=0, background=BG)

    # ------------------------------------------------------------ building
    def _reg(self, widget: tk.Misc, key: str, attr: str = "text") -> tk.Misc:
        self._texts.append((widget, key, attr))
        return widget

    def _entry(self, parent: tk.Misc, variable: tk.StringVar | None = None) -> tk.Entry:
        return tk.Entry(parent, textvariable=variable, bg=NORMAL_BG, fg=TEXT, relief="flat", bd=0,
                        highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT,
                        insertbackground=TEXT, font=self.font_body)

    def _build(self) -> None:
        root = self.root
        p = self.px
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        # ---- header
        head = ttk.Frame(root, padding=(p(16), p(12), p(16), p(6)))
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(1, weight=1)
        self._reg(ttk.Label(head, style="Title.TLabel"), "app_title").grid(row=0, column=0, sticky="w")
        self.lbl_drop = ttk.Label(head, style="Muted.TLabel")
        # the header row is full at the smallest window: the hint shortens itself with "…"
        self.lbl_drop.grid(row=0, column=1, sticky="ew", padx=(p(16), p(12)))
        self.lbl_drop.bind("<Configure>", lambda _e: self._fit_drop_hint())
        self._reg(ttk.Label(head, style="Muted.TLabel"), "country_label").grid(row=0, column=2, padx=(0, p(6)))
        self.cmb_country = ttk.Combobox(head, state="readonly", width=5, textvariable=self.var_country, values=list(COUNTRIES))
        self.cmb_country.grid(row=0, column=3, padx=(0, p(18)))
        self.cmb_country.bind("<<ComboboxSelected>>", self._on_country)
        self._reg(ttk.Label(head, style="Muted.TLabel"), "lbl_language").grid(row=0, column=4, padx=(0, p(6)))
        self.cmb_lang = ttk.Combobox(head, state="readonly", width=10, textvariable=self.var_lang,
                                     values=[i18n.LANG_NAMES[c] for c in i18n.LANGS])
        self.cmb_lang.grid(row=0, column=5)
        self.chk_update = self._reg(ttk.Checkbutton(head, variable=self.var_update_check, command=self._on_update_toggle),
                                    "opt_update_check")
        self.chk_update.grid(row=0, column=6, padx=(p(14), 0))
        self.btn_feedback = self._reg(ttk.Button(head, command=self.open_feedback, style="Feedback.TButton"),
                                      "btn_feedback")
        self.btn_feedback.grid(row=0, column=7, padx=(p(10), 0))
        # Tab reaches it after the update option; Space presses it (ttk), Enter too
        for key in ("<Return>", "<KP_Enter>"):
            self.btn_feedback.bind(key, self._press_feedback)
        self.tip_feedback = Tooltip(self.btn_feedback, lambda: t("feedback_tip"), self.font_small, p)
        self.cmb_lang.bind("<<ComboboxSelected>>", self._on_lang)

        # ---- top / bottom split
        self.paned = ttk.PanedWindow(root, orient="vertical")
        self.paned.grid(row=1, column=0, sticky="nsew", padx=p(16), pady=(p(4), p(6)))

        top = ttk.LabelFrame(self.paned, padding=p(12))
        self._reg(top, "section_current")
        self.paned.add(top, weight=0)  # keeps its height; the table below takes the rest
        top.columnconfigure(2, weight=1)
        top.rowconfigure(0, weight=1)

        # file list (only shown for several files)
        self.frm_files = ttk.Frame(top)
        self.frm_files.grid(row=0, column=0, sticky="nsw", padx=(0, p(14)))
        self.frm_files.rowconfigure(1, weight=1)
        self._reg(ttk.Label(self.frm_files, style="Muted.TLabel"), "lbl_files").grid(row=0, column=0, sticky="w", pady=(0, p(4)))
        self.lst_files = tk.Listbox(self.frm_files, width=34, activestyle="none", exportselection=False,
                                    bg=CARD, fg=TEXT, bd=0, highlightthickness=1, highlightbackground=BORDER,
                                    highlightcolor=BORDER, selectbackground="#dbeafe", selectforeground=TEXT,
                                    font=self.font_body)
        self.lst_files.grid(row=1, column=0, sticky="nsw")
        sb = ttk.Scrollbar(self.frm_files, orient="vertical", command=self.lst_files.yview)
        sb.grid(row=1, column=1, sticky="ns")
        self.lst_files.configure(yscrollcommand=sb.set)
        self.lst_files.bind("<<ListboxSelect>>", self._on_file_select)
        fbtns = ttk.Frame(self.frm_files)
        fbtns.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(p(6), 0))
        self.btn_add = self._reg(ttk.Button(fbtns, command=self._add_files_dialog), "btn_add_files")
        self.btn_add.pack(side="left")
        self.btn_add_dir = self._reg(ttk.Button(fbtns, command=self._add_folder_dialog), "btn_add_folder")
        self.btn_add_dir.pack(side="left", padx=p(4))
        self.btn_clear = self._reg(ttk.Button(fbtns, command=self.clear_files), "btn_clear")
        self.btn_clear.pack(side="left")

        # cover
        cov = ttk.Frame(top)
        cov.grid(row=0, column=1, sticky="n", padx=(0, p(16)))
        self.lbl_cover = tk.Label(cov, image=self._placeholder, bg=CARD, bd=0, highlightthickness=1,
                                  highlightbackground=BORDER)
        self.lbl_cover.pack()
        self.btn_cover = self._reg(ttk.Button(cov, command=self._cover_dialog), "btn_cover_file")
        self.btn_cover.pack(fill="x", pady=(p(8), 0))
        # shown only when the list holds several files (see _refresh_list)
        self.btn_cover_all = self._reg(ttk.Button(cov, command=self.apply_cover_to_all), "btn_cover_all")

        # fields
        fields = ttk.Frame(top)
        fields.grid(row=0, column=2, sticky="nsew")
        fields.columnconfigure(1, weight=1)
        self.lbl_file_info = ttk.Label(fields, style="Small.TLabel")
        self.lbl_file_info.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, p(8)))
        self.entries: dict[str, tk.Entry] = {}
        for i, f in enumerate(tags.FIELDS, start=1):
            self._reg(ttk.Label(fields, style="Muted.TLabel"), f"field_{f}").grid(row=i, column=0, sticky="w", padx=(0, p(10)), pady=p(3))
            e = self._entry(fields, self.var_fields[f])
            e.grid(row=i, column=1, sticky="ew", pady=p(3), ipady=p(3))
            self.var_fields[f].trace_add("write", lambda *_a, f=f: self._on_field_edit(f))
            self.entries[f] = e
        # read-only: which identity tags (MusicBrainz / iTunes IDs, sort name) the file has or will get
        self.lbl_ids = ttk.Label(fields, style="Small.TLabel")
        self.lbl_ids.grid(row=len(tags.FIELDS) + 1, column=0, columnspan=2, sticky="w", pady=(p(4), 0))
        lrow = ttk.Frame(fields)
        lrow.grid(row=len(tags.FIELDS) + 2, column=0, columnspan=2, sticky="w", pady=(p(2), 0))
        self.lbl_lyrics = ttk.Label(lrow, style="Small.TLabel")
        self.lbl_lyrics.pack(side="left")
        # packed only while the file has lyrics (see _update_lyrics_info)
        self.btn_view_lyrics = self._reg(ttk.Button(lrow, command=self.view_lyrics, style="Small.TButton"),
                                         "btn_view_lyrics")

        bottom = ttk.LabelFrame(self.paned, padding=p(12))
        self._reg(bottom, "section_candidates")
        self.paned.add(bottom, weight=1)
        # the top pane must show the cover and all seven fields; set the sash once the window is mapped
        root.after(50, lambda: self.paned.sashpos(0, p(TOP_PANE_PX)))
        bottom.columnconfigure(0, weight=1)
        bottom.rowconfigure(1, weight=1)

        srow = ttk.Frame(bottom)
        srow.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, p(8)))
        srow.columnconfigure(0, weight=1)
        self.ent_query = self._entry(srow, self.var_query)
        self.ent_query.grid(row=0, column=0, sticky="ew", ipady=p(4))
        self.ent_query.bind("<Return>", lambda _e: self.search_text())
        self.btn_search = self._reg(ttk.Button(srow, command=self.search_text, style="Accent.TButton"), "btn_search")
        self.btn_search.grid(row=0, column=1, padx=(p(8), 0))
        self.btn_fp = self._reg(ttk.Button(srow, command=self.search_sound), "btn_fingerprint")
        self.btn_fp.grid(row=0, column=2, padx=(p(6), 0))
        self.btn_cancel = self._reg(ttk.Button(srow, command=self.cancel, state="disabled"), "btn_cancel")
        self.btn_cancel.grid(row=0, column=3, padx=(p(6), 0))

        self.columns = ("title", "artist", "album", "year", "source", "match")
        self.tree = ttk.Treeview(bottom, columns=self.columns, selectmode="browse")
        self.tree.column("#0", width=p(THUMB_PX + 20), stretch=False, anchor="center")
        widths = {"title": 260, "artist": 180, "album": 220, "year": 64, "source": 150, "match": 72}
        for col in self.columns:
            self.tree.column(col, width=p(widths[col]), anchor="center" if col in ("year", "match") else "w",
                             stretch=col in ("title", "artist", "album"))
        self.tree.grid(row=1, column=0, sticky="nsew")
        tsb = ttk.Scrollbar(bottom, orient="vertical", command=self.tree.yview)
        tsb.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=tsb.set)
        self.tree.bind("<Double-1>", lambda _e: self.apply_selected())
        self.tree.bind("<Return>", lambda _e: self.apply_selected())
        self.tree.bind("<Motion>", self._on_tree_motion)
        self.tree.bind("<Leave>", lambda _e: self._hide_preview())
        self.tree.bind("<MouseWheel>", lambda _e: self._hide_preview(), add="+")
        self.tree.tag_configure("odd", background=STRIPE)
        self.tree.tag_configure("good", foreground=GOOD_FG)
        self.tree.tag_configure("fair", foreground=FAIR_FG)
        # floats over the table while the current file's search is still running
        self.lbl_loading = tk.Label(self.tree, bg=CARD, fg=MUTED, font=self.font_bold, padx=p(16), pady=p(10))
        self._loading_shown = False
        self._loading_tick = 0

        # ---- action bar
        bar = ttk.Frame(root, padding=(p(16), p(6), p(16), p(12)))
        bar.grid(row=2, column=0, sticky="ew")
        bar.columnconfigure(5, weight=1)
        self.btn_apply = self._reg(ttk.Button(bar, command=self.apply_selected, style="Accent.TButton"), "btn_apply")
        self.btn_apply.grid(row=0, column=0)
        self.btn_save = self._reg(ttk.Button(bar, command=self.save_current, style="Accent.TButton"), "btn_save")
        self.btn_save.grid(row=0, column=1, padx=(p(8), 0))
        self.btn_save_all = self._reg(ttk.Button(bar, command=self.save_all), "btn_save_all")
        self.btn_save_all.grid(row=0, column=2, padx=(p(8), 0))
        self.btn_undo = self._reg(ttk.Button(bar, command=self.undo_current), "btn_undo")
        self.btn_undo.grid(row=0, column=3, padx=(p(8), 0))
        opts = ttk.Frame(bar)
        opts.grid(row=0, column=4, columnspan=2, sticky="w", padx=(p(20), 0))
        self.chk_rename = self._reg(ttk.Checkbutton(opts, variable=self.var_rename, command=self._save_prefs), "opt_rename")
        self.chk_rename.pack(side="left")
        self.chk_alert = self._reg(ttk.Checkbutton(opts, variable=self.var_save_alert, command=self._save_prefs), "opt_save_alert")
        self.chk_alert.pack(side="left", padx=(p(12), 0))
        self.chk_lyrics = self._reg(ttk.Checkbutton(opts, variable=self.var_lyrics, command=self._on_lyrics_toggle), "opt_lyrics")
        self.chk_lyrics.pack(side="left", padx=(p(12), 0))
        # "!" next to the option: what lyrics are fetched from, when they are not added, copyright
        self.btn_lyrics_notice = ttk.Button(opts, text="!", width=2, style="Notice.TButton", command=self.show_lyrics_notice)
        self.btn_lyrics_notice.pack(side="left", padx=(p(4), 0))
        # progress and status get a row of their own so long messages are not cut off
        self.progress = ttk.Progressbar(bar, mode="determinate", length=p(220))
        self.progress.grid(row=1, column=0, columnspan=2, sticky="w", pady=(p(10), 0))
        self.lbl_status = ttk.Label(bar, anchor="w", style="Muted.TLabel")
        self.lbl_status.grid(row=1, column=2, columnspan=4, sticky="ew", padx=(p(10), 0), pady=(p(10), 0))
        self.lbl_mem = ttk.Label(bar, anchor="e", style="Small.TLabel")
        self.lbl_mem.grid(row=1, column=6, sticky="e", padx=(p(10), 0), pady=(p(10), 0))
        self.root.after(1000, self._tick_memory)

        # ---- one-line "new version" notice under the action bar (gridded only when there is one)
        self.frm_update = tk.Frame(root, bg=UPDATE_BG, highlightthickness=1, highlightbackground=UPDATE_BORDER)
        self.lbl_update = tk.Label(self.frm_update, bg=UPDATE_BG, fg=TEXT, font=self.font_body, anchor="w")
        self.lbl_update.pack(side="left", fill="x", expand=True, padx=(p(12), p(8)), pady=p(6))
        self.btn_update_later = self._reg(ttk.Button(self.frm_update, command=self._update_later), "btn_later")
        self.btn_update_later.pack(side="right", padx=(p(6), p(10)), pady=p(5))
        self.btn_update_open = self._reg(ttk.Button(self.frm_update, command=self._update_open, style="Accent.TButton"),
                                         "btn_update")
        self.btn_update_open.pack(side="right", pady=p(5))

        if _HAS_DND:
            for w in (root, self.lst_files, self.tree, self.lbl_cover):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self._on_drop)

    def _apply_texts(self) -> None:
        self.root.title(t("app_title"))
        for widget, key, attr in self._texts:
            try:
                widget.configure(**{attr: t(key)})
            except tk.TclError:
                pass
        heading_keys = {"title": "field_title", "artist": "field_artist", "album": "field_album",
                        "year": "field_year", "source": "col_source", "match": "col_match"}
        for col, key in heading_keys.items():
            self.tree.heading(col, text=t(key))
        self._fit_drop_hint()
        self.tip_feedback.refresh()
        self._update_file_info()
        if self._status_key:
            self._set_status(self._status_key, **self._status_kwargs)
        if getattr(self, "_update_info", None) is not None:
            self._show_update_notice()

    def _fit_drop_hint(self) -> None:
        full = t("drop_hint")
        width = self.lbl_drop.winfo_width()
        text = full
        if width > 1 and self.font_body.measure(full) > width:
            while text and self.font_body.measure(text.rstrip() + "…") > width:
                text = text[:-1]
            text = text.rstrip() + "…" if text else ""
        if self.lbl_drop.cget("text") != text:
            self.lbl_drop.configure(text=text)

    # ------------------------------------------------------------ helpers
    def _tick_memory(self) -> None:
        if self._closing:
            return
        mb = _working_set_mb()
        self.lbl_mem.configure(text=t("lbl_memory", mb=mb) if mb is not None else "")
        self.root.after(2000, self._tick_memory)

    def _set_status(self, key: str, **kwargs) -> None:
        self._status_key, self._status_kwargs = key, kwargs
        self.lbl_status.configure(text=t(key, **kwargs) if key else "")

    def _set_status_text(self, text: str) -> None:
        """Already-translated composite text (not re-rendered on language change)."""
        self._status_key, self._status_kwargs = "", {}
        self.lbl_status.configure(text=text)

    def _busy(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def _set_loading(self, on: bool, key: str = "msg_loading") -> None:
        self._loading_key = key
        if on and not self._loading_shown:
            self._loading_shown = True
            self.lbl_loading.place(relx=0.5, rely=0.35, anchor="center")
            self._animate_loading()
        elif not on and self._loading_shown:
            self._loading_shown = False
            self.lbl_loading.place_forget()

    def _animate_loading(self) -> None:
        if not self._loading_shown or self._closing:
            return
        self.lbl_loading.configure(text=t(self._loading_key) + " " + "." * (self._loading_tick % 4))
        self._loading_tick += 1
        self.root.after(400, self._animate_loading)

    def _mark_searching(self, states: list, on: bool) -> None:
        for s in states:
            s.searching = on
        if self.current is not None:
            self._set_loading(self.current.searching)

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for w in (self.btn_search, self.btn_fp, self.btn_apply, self.btn_save, self.btn_save_all, self.btn_undo,
                  self.btn_add, self.btn_add_dir, self.btn_clear, self.btn_cover, self.btn_cover_all,
                  self.btn_view_lyrics):
            w.configure(state=state)
        self.cmb_lang.configure(state="disabled" if busy else "readonly")
        self.cmb_country.configure(state="disabled" if busy else "readonly")
        self.btn_cancel.configure(state="normal" if busy else "disabled")
        if not busy:
            self.progress.configure(value=0)
            self._apply_offline_state()

    def _apply_offline_state(self) -> None:
        if self._offline and not self._busy():
            self.btn_search.configure(state="disabled")
            self.btn_fp.configure(state="disabled")

    def _probe_online(self) -> None:
        ok = net.online()
        self.root.after(0, lambda: self._set_online(ok))

    def _set_online(self, ok: bool) -> None:
        if self._closing:
            return
        self._offline = not ok
        if not ok:
            self._set_status("err_network")
        elif self._status_key == "err_network":
            self._set_status("status_ready")
        self._apply_offline_state()

    def _run(self, target, *args) -> None:
        """Run target(*args) in the worker thread with the buttons locked."""
        if self._busy():
            return
        self.cancel_event.clear()
        self._set_busy(True)
        self.worker = threading.Thread(target=self._guarded, args=(target, *args), daemon=False)
        self.worker.start()

    def _guarded(self, target, *args) -> None:
        try:
            target(*args)
        except Exception as exc:  # never let a worker die silently
            self._ui(self._show_error, str(exc))
        finally:
            self._ui(self._mark_searching, list(self.files), False)
            self._ui(self._set_busy, False)

    def _ui(self, fn, *args, **kwargs) -> None:
        """Call fn on the Tk thread (workers must never touch widgets directly)."""
        if not self._closing:
            try:
                self.root.after(0, lambda: fn(*args, **kwargs))
            except tk.TclError:
                pass

    def _on_wait(self, seconds: float) -> None:
        self._ui(self._set_status, "err_rate_limit", sec=int(round(seconds)))

    def _show_error(self, text: str) -> None:
        if not self._closing:
            messagebox.showerror(t("dlg_error"), text, parent=self.root)

    @staticmethod
    def _fmt_length(seconds: float | None) -> str:
        if not seconds:
            return "-"
        return f"{int(seconds // 60)}:{int(seconds % 60):02d}"

    # ------------------------------------------------------------ files
    def _on_drop(self, event) -> None:
        paths = list(self.root.tk.splitlist(event.data))
        images = [p for p in paths if os.path.splitext(p)[1].lower() in IMAGE_EXTS]
        others = [p for p in paths if p not in images]
        if images and self.current is not None:
            self._set_cover_from_file(images[0])
        if others:
            self.add_paths(others)

    def _add_files_dialog(self) -> None:
        patterns = " ".join(f"*{e}" for e in tags.SUPPORTED_EXTS)
        paths = filedialog.askopenfilenames(parent=self.root, filetypes=[(t("file_dialog_audio"), patterns)])
        if paths:
            self.add_paths(list(paths))

    def _add_folder_dialog(self) -> None:
        folder = filedialog.askdirectory(parent=self.root)
        if folder:
            self.add_paths([folder])

    def add_paths(self, paths: list[str]) -> None:
        if self._busy():
            return
        recurse = True
        if any(os.path.isdir(p) for p in paths):
            recurse = messagebox.askyesno(t("dlg_confirm"), t("warn_recurse"), parent=self.root)
        found = tags.collect_files(paths, recurse=recurse)
        known = {os.path.normcase(f.path) for f in self.files}
        new = [p for p in found if os.path.normcase(p) not in known]
        if not new:
            if not found:
                self._set_status("msg_no_files")
            return
        states = [FileState(path=p) for p in new]
        self.files.extend(states)
        for s in states:
            self.lst_files.insert("end", "")
        self._refresh_list()
        self._run(self._load_and_search, states, len(self.files) > 1)

    def clear_files(self) -> None:
        if self._busy():
            return
        self.files = []
        self.lst_files.delete(0, "end")
        self._set_loading(False)
        self._thumbs.clear()
        self._thumb_misses.clear()
        self._thumb_rows = {}
        self._preview_cache.clear()
        self._preview_misses.clear()
        self.covers.close()
        self._show_file(None)
        self._refresh_list()

    def _refresh_list(self) -> None:
        show = len(self.files) > 1
        if show:
            self.frm_files.grid()
        else:
            self.frm_files.grid_remove()
        if show and not self.btn_cover_all.winfo_ismapped():
            self.btn_cover_all.pack(fill="x", pady=(self.px(6), 0), after=self.btn_cover)
        elif not show and self.btn_cover_all.winfo_manager():
            self.btn_cover_all.pack_forget()
        # Update rows in place: deleting and re-inserting every row on each refresh
        # made the list jump and flicker whenever a file was clicked or a field edited.
        lst = self.lst_files
        top = lst.yview()[0]
        for i, s in enumerate(self.files):
            mark = CHECK if (s.confirmed or s.auto or s.saved) else " "
            label = f" {mark} {s.name()}"
            if i >= lst.size():
                lst.insert("end", label)
            elif lst.get(i) != label:
                lst.delete(i)
                lst.insert(i, label)
            fg = DONE_FG if s.saved else AUTO_FG if (s.auto and not s.confirmed) else TEXT
            if lst.itemcget(i, "foreground") != fg:
                lst.itemconfig(i, foreground=fg)
        while lst.size() > len(self.files):
            lst.delete("end")
        if self.current is not None and self.current in self.files:
            idx = self.files.index(self.current)
            if tuple(lst.curselection()) != (idx,):
                lst.selection_clear(0, "end")
                lst.selection_set(idx)
        lst.yview_moveto(top)

    def _on_file_select(self, _event=None) -> None:
        sel = self.lst_files.curselection()
        if sel and 0 <= sel[0] < len(self.files):
            self._show_file(self.files[sel[0]])

    # ------------------------------------------------------------ loading + batch search
    def _load_and_search(self, states: list[FileState], batch: bool) -> None:
        total = len(states)
        first_shown = False
        net_error = False
        self._ui(self._mark_searching, states, True)
        for idx, s in enumerate(states, 1):
            if self.cancel_event.is_set():
                break
            try:
                s.attach_info(tags.read_file(s.path))
                s.query = pipeline.query_text(s.info)
            except Exception:
                s.error = "err_open_failed"
                self._ui(self._mark_searching, [s], False)
                self._ui(self._refresh_list)
                continue
            if not first_shown and self.current is None:
                first_shown = True
                self._ui(self._show_file, s)
            self._ui(self._set_status, "status_batch", index=idx, total=total, name=s.name())
            self._ui(self.progress.configure, {"value": 100.0 * (idx - 1) / total})
            if self._offline or not s.query:
                self._ui(self._mark_searching, [s], False)
                continue
            result = pipeline.search_text(s.query, self._country, s.info.length,
                                          on_wait=self._on_wait, cancel=self.cancel_event)
            s.result, s.candidates = result, result.candidates
            s.searching = False
            if pipeline.ERR_NETWORK in result.errors and not result.candidates:
                net_error = True
            if batch:
                pick = pipeline.auto_pick(result)
                if pick is not None:
                    # an automatic pick only fills what is missing; the user's
                    # existing album, year and cover stay unless they apply by hand
                    s.selected, s.auto = pick, True
                    self._apply_values(s, pick, overwrite=False)
                    if not s.has_cover:
                        cover = pipeline.fetch_cover(pick, self._country, on_wait=self._on_wait, cancel=self.cancel_event)
                        if cover:
                            s.cover_key, s.cover_changed = self.covers.put(cover), True
            self._ui(self._after_file_loaded, s)
        auto = sum(1 for s in states if s.auto)
        self._ui(self._mark_searching, states, False)  # cancelled or skipped files must not spin forever
        if self.cancel_event.is_set():
            self._ui(self._set_status, "status_cancelled")
        elif self._offline or net_error:
            self._ui(self._set_online, False)  # searching is off, editing and saving still work
        else:
            self._ui(self._set_status, "msg_batch_done", auto=auto, total=total)
        self._ui(self._refresh_list)

    def _after_file_loaded(self, s: FileState) -> None:
        self._refresh_list()
        if s is self.current:
            self._show_file(s)

    # ------------------------------------------------------------ showing a file
    def _show_file(self, s: FileState | None) -> None:
        self.current = s
        self._loading_entries = True
        try:
            for f in tags.FIELDS:
                self.var_fields[f].set(s.values.get(f, "") if s else "")
            self.var_query.set(s.query if s else "")
        finally:
            self._loading_entries = False
        self._update_file_info()
        self._paint_fields()
        self._show_cover(s.load_cover() if s else None)
        self._fill_tree(s.candidates if s else [])
        self._set_loading(bool(s and s.searching))
        if s and s.error:
            self._set_status(s.error, name=s.name())
        elif s and s.result and not s.candidates:
            self._set_status("msg_no_results")
        self._refresh_list()

    def _update_file_info(self) -> None:
        s = self.current
        if s is None or s.info is None:
            self.lbl_file_info.configure(text="")
            self.lbl_ids.configure(text="")
            return
        self.lbl_file_info.configure(text=t("lbl_file_info", name=s.name(), fmt=s.info.fmt,
                                            length=self._fmt_length(s.info.length), bitrate=s.info.bitrate))
        ids = s.final_ids()
        sources = [name for name, present in (("MusicBrainz", bool(ids.mb_artist_ids or ids.mb_recording_id)),
                                              ("iTunes", bool(ids.itunes_artist_id))) if present]
        text = ", ".join(sources) if sources else t("ids_none")
        if ids.artist_sort:
            text += f" ({ids.artist_sort})"
        if s.ids_changed():
            text += " " + t("ids_pending")
        self.lbl_ids.configure(text=t("lbl_ids", text=text))
        self._update_lyrics_info()

    def _update_lyrics_info(self) -> None:
        s = self.current
        if s is None or s.info is None:
            self.lbl_lyrics.configure(text="")
            self.btn_view_lyrics.pack_forget()
            return
        if s.has_lyrics:
            text = t("lyrics_has", lines=s.lyrics_lines)
            if not self.btn_view_lyrics.winfo_manager():
                self.btn_view_lyrics.pack(side="left", padx=(self.px(8), 0))
        else:
            self.btn_view_lyrics.pack_forget()
            status = s.lyrics_status
            title, artist = s.values.get("title", "").strip(), s.values.get("artist", "").strip()
            # a tag holding only a player marker ("[COWON S9]") is treated as empty
            none = t("lyrics_marker", text=s.lyrics_note) if s.lyrics_note else t("lyrics_none")
            if status == search_lyrics.BUSY:
                text = t("lyrics_busy")
            elif status == search_lyrics.NOT_FOUND:
                text = t("lyrics_not_found")
            elif status == search_lyrics.INSTRUMENTAL:
                text = t("lyrics_instrumental")
            elif status == search_lyrics.CONFLICT:
                text = t("lyrics_conflict")
            elif status == search_lyrics.NO_LYRICS:
                text = t("lyrics_no_lyrics")
            elif status == search_lyrics.NEED_TAGS and not (title and artist):
                text = none + " \u00b7 " + t("lyrics_need_tags")
            elif not self.var_lyrics.get():
                text = none
            elif search_lyrics.is_instrumental_title(title):
                text = t("lyrics_instrumental")
            elif not (title and artist):
                text = none + " \u00b7 " + t("lyrics_need_tags")
            else:
                text = none + " " + t("lyrics_on_save")
        self.lbl_lyrics.configure(text=t("lbl_lyrics", text=text))

    def _paint_fields(self) -> None:
        changed = self.current.changed_fields() if self.current else set()
        for f, e in self.entries.items():
            e.configure(bg=CHANGED_BG if f in changed else NORMAL_BG)

    def _on_field_edit(self, field: str) -> None:
        if self._loading_entries or self.current is None:
            return
        self.current.values[field] = self.var_fields[field].get()
        if self.current.auto:
            self.current.confirmed = True
        self.current.saved = False
        if field in ("title", "artist") and self.current.lyrics_status != search_lyrics.FOUND:
            self.current.lyrics_status = ""  # a new title or artist is a new lookup
        self._paint_fields()
        self._update_lyrics_info()
        self._refresh_list()

    def _show_cover(self, data: bytes | None) -> None:
        self._cover_photo = None
        if data:
            try:
                with Image.open(io.BytesIO(data)) as im:
                    im = im.convert("RGB")
                    size = self.px(COVER_PX)
                    im.thumbnail((size, size), Image.LANCZOS)
                    self._cover_photo = ImageTk.PhotoImage(im)
            except Exception:
                self._cover_photo = None
        self.lbl_cover.configure(image=self._cover_photo if self._cover_photo is not None else self._placeholder)

    def apply_cover_to_all(self) -> None:
        """Give every file in the list the cover shown now (an album folder usually
        shares one). Nothing is written until Save / Save all."""
        s = self.current
        if s is None:
            self._set_status("msg_no_files")
            return
        data = s.load_cover()
        if not data:
            self._set_status("msg_no_cover")
            return
        targets = [f for f in self.files if f.info is not None and f is not s]
        if not targets:
            return
        if not messagebox.askyesno(t("dlg_confirm"), t("warn_cover_all", count=len(targets)), parent=self.root):
            return
        # one copy on disk shared by every file, not one per file
        key = s.cover_key if s.cover_changed else self.covers.put(data)
        for f in targets:
            f.cover_key, f.cover_changed, f.saved = key, True, False
            if f.auto:
                f.confirmed = True
        self._refresh_list()
        self._set_status("msg_cover_applied", count=len(targets))

    def _cover_dialog(self) -> None:
        if self.current is None:
            self._set_status("msg_no_files")
            return
        patterns = " ".join(f"*{e}" for e in IMAGE_EXTS)
        path = filedialog.askopenfilename(parent=self.root, filetypes=[(t("file_dialog_image"), patterns)])
        if path:
            self._set_cover_from_file(path)

    def _set_cover_from_file(self, path: str) -> None:
        if self.current is None:
            return
        try:
            with open(path, "rb") as f:
                data = f.read()
            with Image.open(io.BytesIO(data)) as im:
                im.verify()
        except Exception:
            self._set_status("err_open_failed", name=os.path.basename(path))
            return
        self.current.cover_key, self.current.cover_changed, self.current.saved = self.covers.put(data), True, False
        if self.current.auto:
            self.current.confirmed = True
        self._show_cover(data)
        self._refresh_list()

    # ------------------------------------------------------------ candidates table
    def _fill_tree(self, cands: list[Candidate]) -> None:
        self._hide_preview()
        self.tree.delete(*self.tree.get_children())
        self._thumb_rows = {}
        for i, c in enumerate(cands):
            img = self._thumbs.get(c.thumb_url or "")
            row_tags = ["odd"] if i % 2 else []
            if c.score >= 90:
                row_tags.append("good")
            elif c.score >= 70:
                row_tags.append("fair")
            self.tree.insert("", "end", iid=str(i), image=img if img else "",
                             values=(c.title, c.artist, c.album, c.year, c.source_label(), c.score),
                             tags=tuple(row_tags))
            if c.thumb_url and c.thumb_url not in self._thumb_rows:
                self._thumb_rows[c.thumb_url] = str(i)
        if cands:
            self.tree.selection_set("0")
            self.tree.focus("0")
            self._queue_thumbs(cands)

    def _queue_thumbs(self, cands: list[Candidate]) -> None:
        todo = []
        seen: set[str] = set()
        for c in cands:
            url = c.thumb_url
            if not url or url in seen or url in self._thumbs or url in self._thumb_misses or url in self._thumb_inflight:
                continue
            seen.add(url)
            todo.append(c)
        # iTunes art comes from a fast CDN; Cover Art Archive answers through a slow
        # redirect, so the quick ones go first and fill most of the table at once
        todo.sort(key=lambda c: 0 if "mzstatic" in (c.thumb_url or "") else 1)
        for c in todo:
            self._thumb_inflight.add(c.thumb_url)
            self._thumb_pool.submit(self._fetch_thumb, c)

    def _fetch_thumb(self, c: Candidate) -> None:
        if self._closing:
            return
        data = pipeline.fetch_thumb(c)
        self._ui(self._thumb_done, c.thumb_url, data)

    def _thumb_done(self, url: str, data: bytes | None) -> None:
        self._thumb_inflight.discard(url)
        if not data:
            if len(self._thumb_misses) > 5000:
                self._thumb_misses.clear()
            self._thumb_misses.add(url)
            return
        try:
            with Image.open(io.BytesIO(data)) as im:
                im = im.convert("RGB")
                size = self.px(THUMB_PX)
                im.thumbnail((size, size), Image.LANCZOS)
                photo = ImageTk.PhotoImage(im)
        except Exception:
            self._thumb_misses.add(url)
            return
        self._thumbs[url] = photo
        if len(self._thumbs) > 400:
            for key in list(self._thumbs)[:100]:
                del self._thumbs[key]
        iid = self._thumb_rows.get(url)
        if iid is not None and self.tree.exists(iid):
            self.tree.item(iid, image=photo)

    # ------------------------------------------------------------ hover preview
    @staticmethod
    def _preview_url_for(c: Candidate) -> str | None:
        """A mid-size image: iTunes serves any size from the same path; Cover Art
        Archive's front-500 is the candidate's cover URL."""
        if c.thumb_url and "mzstatic" in c.thumb_url:
            return search_itunes.artwork(c.thumb_url, 600)
        return c.cover_url or c.thumb_url

    def _on_tree_motion(self, event) -> None:
        row = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        cand = None
        if row and col == "#0" and self.current is not None:
            try:
                cand = self.current.candidates[int(row)]
            except (ValueError, IndexError):
                cand = None
        url = self._preview_url_for(cand) if cand is not None else None
        if not url or url in self._preview_misses:
            self._hide_preview()
            return
        self._preview_pos = (event.x_root, event.y_root)
        if url == self._preview_url:
            if self._preview_win is not None and self._preview_win.winfo_viewable():
                self._place_preview()
            return
        self._hide_preview()
        self._preview_url = url
        self._preview_job = self.root.after(PREVIEW_DELAY_MS, self._show_preview)

    def _ensure_preview_win(self) -> None:
        if self._preview_win is not None:
            return
        win = tk.Toplevel(self.root)
        win.withdraw()
        win.overrideredirect(True)
        try:
            win.attributes("-topmost", True)
        except tk.TclError:
            pass
        win.configure(bg=BORDER)
        self._preview_lbl = tk.Label(win, bg=CARD, fg=MUTED, font=self.font_body, bd=0,
                                     padx=self.px(6), pady=self.px(6))
        self._preview_lbl.pack(padx=1, pady=1)
        self._preview_win = win

    def _place_preview(self) -> None:
        win = self._preview_win
        if win is None:
            return
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        x, y = self._preview_pos[0] + self.px(24), self._preview_pos[1] - h // 2
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        if x + w > sw:
            x = self._preview_pos[0] - self.px(24) - w  # flip to the left of the cursor
        y = max(0, min(y, sh - h))
        win.geometry(f"+{x}+{y}")

    def _show_preview(self) -> None:
        self._preview_job = None
        url = self._preview_url
        if not url or self._closing:
            return
        self._ensure_preview_win()
        photo = self._preview_cache.get(url)
        if photo is not None:
            self._preview_lbl.configure(image=photo, text="")
        else:
            self._preview_lbl.configure(image="", text=t("msg_loading") + " ...",
                                        width=self.px(PREVIEW_PX) // 8, height=self.px(PREVIEW_PX) // 20)
            self._thumb_pool.submit(self._fetch_preview, url)
        self._place_preview()
        self._preview_win.deiconify()
        self._preview_win.lift()

    def _fetch_preview(self, url: str) -> None:
        if self._closing:
            return
        try:
            data = net.get_bytes(url, max_bytes=5 * 1024 * 1024)
        except (net.NetworkError, net.RateLimited):
            data = None
        self._ui(self._preview_done, url, data)

    def _preview_done(self, url: str, data: bytes | None) -> None:
        photo = None
        if data:
            try:
                with Image.open(io.BytesIO(data)) as im:
                    im = im.convert("RGB")
                    size = self.px(PREVIEW_PX)
                    im.thumbnail((size, size), Image.LANCZOS)
                    photo = ImageTk.PhotoImage(im)
            except Exception:
                photo = None
        if photo is None:
            self._preview_misses.add(url)
            if url == self._preview_url:
                self._hide_preview()
            return
        self._preview_cache[url] = photo
        if len(self._preview_cache) > 40:  # a few MB at most
            for key in list(self._preview_cache)[:10]:
                del self._preview_cache[key]
        if url == self._preview_url and self._preview_win is not None and self._preview_win.winfo_viewable():
            self._preview_lbl.configure(image=photo, text="", width=0, height=0)
            self._place_preview()

    def _hide_preview(self) -> None:
        if self._preview_job is not None:
            try:
                self.root.after_cancel(self._preview_job)
            except tk.TclError:
                pass
            self._preview_job = None
        self._preview_url = None
        if self._preview_win is not None:
            self._preview_win.withdraw()

    def _selected_candidate(self) -> Candidate | None:
        sel = self.tree.selection()
        if not sel or self.current is None:
            return None
        try:
            return self.current.candidates[int(sel[0])]
        except (ValueError, IndexError):
            return None

    # ------------------------------------------------------------ searching
    def search_text(self) -> None:
        s = self.current
        if s is None or s.info is None:
            self._set_status("msg_no_files")
            return
        query = self.var_query.get().strip()
        if not query:
            return
        s.query = query
        s.candidates, s.result = [], None
        self._fill_tree([])
        self._set_status("msg_searching")
        self._mark_searching([s], True)
        self._run(self._search_text_job, s, query)

    def _search_text_job(self, s: FileState, query: str) -> None:
        if self._offline and not net.online():
            self._ui(self._mark_searching, [s], False)
            self._ui(self._set_online, False)
            return
        self._ui(self._set_online, True)
        result = pipeline.search_text(query, self._country, s.info.length,
                                      on_wait=self._on_wait, cancel=self.cancel_event)
        self._ui(self._search_done, s, result)

    def search_sound(self) -> None:
        s = self.current
        if s is None or s.info is None:
            self._set_status("msg_no_files")
            return
        self._set_status("msg_searching")
        self._mark_searching([s], True)
        self._set_loading(True, "msg_fingerprinting")
        self._run(self._search_sound_job, s, self.var_query.get().strip())

    def _search_sound_job(self, s: FileState, query: str = "") -> None:
        result = pipeline.search_sound(s.path, self.prefs, query, s.info.length,
                                       on_wait=self._on_wait, cancel=self.cancel_event)
        if result.candidates and s.candidates:
            # fingerprint hits join the text-search rows; rank() merges duplicates and re-sorts
            result.candidates = match.rank(result.candidates + s.candidates, result.query_title,
                                           result.query_artist, s.info.length)
        self._ui(self._search_done, s, result)

    def _search_done(self, s: FileState, result: pipeline.SearchResult) -> None:
        s.result, s.candidates = result, result.candidates
        self._mark_searching([s], False)
        if self.cancel_event.is_set():
            self._set_status("status_cancelled")
        elif result.errors:
            self._set_status(result.errors[0], sec=0)
        elif not result.candidates:
            self._set_status("msg_no_results")
        else:
            self._set_status("msg_results", count=len(result.candidates))
        if s is self.current:
            self._fill_tree(s.candidates)

    def cancel(self) -> None:
        self.cancel_event.set()
        self._set_status("status_cancelled")

    # ------------------------------------------------------------ apply / save / undo
    def _apply_values(self, s: FileState, cand: Candidate, overwrite: bool = True) -> None:
        latin = self.prefs.artist_name_preference == "latin"
        s.values = pipeline.apply_candidate(s.current_tags(), cand, overwrite, latin).as_dict()
        # IDs are written for automatic picks too: an ID is an empty field being filled.
        # Editing the artist text by hand afterwards keeps them (text is display, ID is identity).
        s.pending_ids = pipeline.ids_from_candidate(cand)
        s.saved = False
        if s.lyrics_status != search_lyrics.FOUND:
            s.lyrics_status = ""

    def apply_selected(self) -> None:
        s = self.current
        cand = self._selected_candidate()
        if s is None or cand is None:
            self._set_status("msg_no_selection")
            return
        s.selected, s.auto, s.confirmed = cand, False, True
        self._apply_values(s, cand)
        self._show_file(s)
        if cand.cover_url or cand.album:  # the album name alone can find a cover (iTunes fallback)
            self._run(self._fetch_cover_job, s, cand)

    def _fetch_cover_job(self, s: FileState, cand: Candidate) -> None:
        data = pipeline.fetch_cover(cand, self._country, on_wait=self._on_wait, cancel=self.cancel_event)
        if data:
            s.cover_key, s.cover_changed = self.covers.put(data), True
            if s is self.current:
                self._ui(self._show_cover, data)
        else:
            self._ui(self._set_status, "msg_cover_failed")

    def save_current(self) -> None:
        s = self.current
        if s is None or s.info is None:
            self._set_status("msg_no_files")
            return
        want = bool(self.var_lyrics.get())
        if not s.dirty() and not (want and s.lyrics_wanted()):
            self._set_status("msg_nothing_to_save")
            return
        self._run(self._save_job, [s], want, bool(self.var_rename.get()))

    def save_all(self) -> None:
        want = bool(self.var_lyrics.get())
        todo = [s for s in self.files if s.info is not None
                and ((s.dirty() and not s.saved) or (want and s.lyrics_wanted()))]
        if not todo:
            self._set_status("msg_nothing_to_save")
            return
        self._run(self._save_job, todo, want, bool(self.var_rename.get()))

    def _write_state(self, s: FileState, lyrics: str | None, rename: bool) -> tuple[str, pipeline.SaveResult | None]:
        """Save one file's pending changes (and lyrics). ('ok' | 'locked' | 'broken' | 'error', result)."""
        try:
            res = pipeline.save_file(s.path, s.current_tags(), s.load_cover() if s.cover_changed else None,
                                     self.prefs, rename=rename, ids=s.pending_ids, lyrics=lyrics)
        except tags.BrokenBackup:
            return "broken", None
        except tags.FileLocked:
            return "locked", None
        except Exception as exc:  # unexpected: the log says what, the user sees which file
            pipeline.log_error(f"save {s.path}", exc)
            return "error", None
        s.path = res.path
        s.cover_key, s.cover_changed, s.pending_ids = None, False, None
        s.saved, s.auto, s.confirmed = True, False, True
        try:
            s.attach_info(tags.read_file(s.path))
        except Exception as exc:  # saved, but gone or locked by another program right after
            pipeline.log_error(f"read after save {s.path}", exc)
            s.error = "err_open_failed"
        return "ok", res

    def _save_job(self, states: list[FileState], want_lyrics: bool = False, rename: bool = False) -> None:
        """Worker thread: never reads Tk variables (the options come in as arguments)."""
        written: set[int] = set()
        failed: list[str] = []
        broken: list[str] = []
        errored: list[str] = []
        not_renamed: list[str] = []
        cover_failed = 0
        last_backup = ""
        looked_up: dict[int, FileState] = {}
        lyrics_added = 0
        busy_streak = 0
        retry: list[FileState] = []
        total = len(states)

        def record(s: FileState, kind: str, res: pipeline.SaveResult | None) -> bool:
            nonlocal cover_failed, last_backup
            if kind == "broken":
                broken.append(s.name())
            elif kind == "error":
                errored.append(s.name())
            elif kind != "ok" or res is None:
                failed.append(s.name())
            else:
                written.add(id(s))
                last_backup = os.path.basename(res.backup)
                if res.rename_failed:
                    not_renamed.append(s.name())
                if res.cover_failed:
                    cover_failed += 1
                return True
            return False

        for idx, s in enumerate(states, 1):
            if self.cancel_event.is_set():
                break
            self._ui(self.progress.configure, {"value": 100.0 * (idx - 1) / total})
            text: str | None = None
            if want_lyrics and s.lyrics_wanted():
                looked_up[id(s)] = s
                if busy_streak >= LYRICS_BUSY_LIMIT:
                    s.lyrics_status = search_lyrics.BUSY  # the server is down: do not keep knocking
                else:
                    self._ui(self._set_status, "status_lyrics", index=idx, total=total, name=s.name())
                    found = pipeline.find_lyrics(s.current_tags(), s.info.length, cancel=self.cancel_event)
                    if self.cancel_event.is_set():
                        s.lyrics_status = ""
                        break
                    s.lyrics_status = found.status
                    busy_streak = busy_streak + 1 if found.status == search_lyrics.BUSY else 0
                    if found.status == search_lyrics.FOUND:
                        text = found.text
                    elif found.status == search_lyrics.BUSY:
                        retry.append(s)
            if text is None and not s.dirty():
                continue  # only lyrics were wanted and none came: the file is not touched
            self._ui(self._set_status, "status_saving", index=idx, total=total, name=s.name())
            kind, res = self._write_state(s, text, rename)
            if record(s, kind, res) and text is not None:
                lyrics_added += 1
            elif text is not None:
                s.lyrics_status = ""  # not written: look again next time

        # one more try for the songs the server was too busy for, unless it looked down
        if retry and busy_streak < LYRICS_BUSY_LIMIT and not self.cancel_event.is_set():
            busy_streak = 0
            for idx, s in enumerate(retry, 1):
                if self.cancel_event.is_set() or busy_streak >= LYRICS_BUSY_LIMIT:
                    break
                self._ui(self._set_status, "status_lyrics_retry", index=idx, total=len(retry), name=s.name())
                self._ui(self.progress.configure, {"value": 100.0 * (idx - 1) / len(retry)})
                found = pipeline.find_lyrics(s.current_tags(), s.info.length, cancel=self.cancel_event)
                if self.cancel_event.is_set():
                    break
                s.lyrics_status = found.status
                busy_streak = busy_streak + 1 if found.status == search_lyrics.BUSY else 0
                if found.status != search_lyrics.FOUND:
                    continue
                # the file was already renamed (or not) in the first pass
                kind, res = self._write_state(s, found.text, rename=False)
                if record(s, kind, res):
                    lyrics_added += 1
                else:
                    s.lyrics_status = ""
        counts = {"added": lyrics_added}
        for key, status in (("none", search_lyrics.NOT_FOUND), ("busy", search_lyrics.BUSY),
                            ("inst", search_lyrics.INSTRUMENTAL), ("conflict", search_lyrics.CONFLICT),
                            ("nolyr", search_lyrics.NO_LYRICS)):
            counts[key] = sum(1 for st in looked_up.values() if st.lyrics_status == status)
        self._ui(self._save_done, len(written), failed, cover_failed, last_backup, broken, not_renamed,
                 counts if want_lyrics and looked_up else None, errored, self.cancel_event.is_set())

    def _save_done(self, saved: int, failed: list[str], cover_failed: int, last_backup: str,
                   broken: list[str] | None = None, not_renamed: list[str] | None = None,
                   lyrics: dict | None = None, errored: list[str] | None = None, cancelled: bool = False) -> None:
        self._refresh_list()
        if self.current is not None:
            self._show_file(self.current)
        # most important first: the status line is one row and a long file name cuts off the end
        lines = [t("msg_saved", count=saved)] if (saved or not lyrics) else []
        if cancelled:
            lines.insert(0, t("status_cancelled"))
        if lyrics:
            parts = [t(msg, count=lyrics[key]) for key, msg in (
                ("added", "msg_lyrics_added"), ("none", "msg_lyrics_none"),
                ("busy", "msg_lyrics_busy"), ("inst", "msg_lyrics_inst"),
                ("conflict", "msg_lyrics_conflict"), ("nolyr", "msg_lyrics_nolyrics")) if lyrics.get(key)]
            if parts:
                lines.append(t("lbl_lyrics", text=", ".join(parts)))
        if failed:
            lines.append(t("err_readonly") + ": " + ", ".join(failed))
        if broken:
            lines.append(t("err_backup_broken") + ": " + ", ".join(broken))
        if errored:
            lines.append(t("err_save_failed") + ": " + ", ".join(errored))
        if not_renamed:
            lines.append(t("msg_not_renamed") + ": " + ", ".join(not_renamed))
        if cover_failed:
            lines.append(t("msg_cover_failed"))
        if saved and last_backup:
            lines.append(t("msg_backup_note", file=last_backup))
        self._set_status_text(" \u00b7 ".join(lines))
        if self._closing:
            return
        if failed or broken or errored:
            messagebox.showerror(t("dlg_error"), "\n".join(lines), parent=self.root)
        elif not_renamed:
            messagebox.showwarning(t("dlg_done"), "\n".join(lines), parent=self.root)
        elif self.var_save_alert.get():
            messagebox.showinfo(t("dlg_done"), "\n".join(lines), parent=self.root)

    def undo_current(self) -> None:
        s = self.current
        if s is None:
            self._set_status("msg_no_files")
            return
        if not os.path.exists(tags.backup_path(s.path)):
            self._set_status("msg_no_backup", name=s.name())
            return
        self._run(self._undo_job, s)

    def _undo_job(self, s: FileState) -> None:
        try:
            exact = tags.restore_backup(s.path)
        except tags.NoBackup:
            self._ui(self._set_status, "msg_no_backup", name=s.name())
            return
        except tags.FileLocked:
            self._ui(self._set_status, "err_readonly")
            return
        try:
            s.attach_info(tags.read_file(s.path))
        except Exception as exc:  # restored, but the file cannot be read back right now
            pipeline.log_error(f"read after undo {s.path}", exc)
            s.error = "err_open_failed"
        s.cover_key, s.cover_changed, s.pending_ids = None, False, None
        s.saved, s.auto, s.confirmed, s.selected = False, False, False, None
        s.lyrics_status = ""
        self._ui(self._undo_done, s, exact)

    def _undo_done(self, s: FileState, exact: bool) -> None:
        if s is self.current:
            self._show_file(s)
        self._set_status("msg_restored_exact" if exact else "msg_restored_tags", name=s.name())

    # ------------------------------------------------------------ settings
    def _save_prefs(self) -> None:
        self.prefs.rename = bool(self.var_rename.get())
        self.prefs.save_alert = bool(self.var_save_alert.get())
        self.prefs.lyrics = bool(self.var_lyrics.get())
        self.prefs.update_check = bool(self.var_update_check.get())
        self.prefs.country = self.var_country.get()
        prefs_mod.save(self.prefs)

    # ------------------------------------------------------------ new version notice
    def _on_update_result(self, info: update_check.UpdateInfo | None, answered: bool) -> None:
        """Tk thread. The day is recorded only when the server answered, so an offline
        start asks again next time."""
        if self._closing:
            return
        if answered:
            self.prefs.update_check_last = update_check.today()
            self._save_prefs()
        if info is not None and self.var_update_check.get():
            self._update_info = info
            self._show_update_notice()

    def _show_update_notice(self) -> None:
        info = self._update_info
        if info is None:
            self.frm_update.grid_remove()
            return
        self.lbl_update.configure(text=t("update_available", latest=info.latest, current=info.current))
        if self.frm_update.winfo_manager():
            return
        # The row takes height from the split pane, which gives it up from the top: without
        # this the file-info pane collapsed to nothing when the notice appeared.
        try:
            sash = self.paned.sashpos(0)
        except tk.TclError:
            sash = self.px(TOP_PANE_PX)
        self.frm_update.grid(row=3, column=0, sticky="ew", padx=self.px(16), pady=(0, self.px(10)))
        self.root.after_idle(lambda: self._restore_sash(sash))

    def _restore_sash(self, pos: int) -> None:
        try:
            # back where it was; a position that small means the pane had not been laid out yet
            self.paned.sashpos(0, pos if pos > self.px(150) else self.px(TOP_PANE_PX))
        except tk.TclError:
            pass

    def _hide_update_notice(self) -> None:
        self._update_info = None
        self.frm_update.grid_remove()

    def _update_open(self) -> None:
        """The tools page, never a download: the site counts and serves the download."""
        info = self._update_info
        if info is not None:
            url = update_check.link_for(info, i18n.current_lang())  # English page unless the screen is Korean
            if url.startswith(update_check.SITE):
                try:
                    webbrowser.open(url)
                except Exception:
                    pass
        self._hide_update_notice()

    def _update_later(self) -> None:
        if self._update_info is not None:
            self.prefs.update_check_skipped = self._update_info.latest  # a newer one is shown again
            self._save_prefs()
        self._hide_update_notice()

    def _on_update_toggle(self) -> None:
        self._save_prefs()
        if not self.var_update_check.get():
            self._hide_update_notice()

    # ------------------------------------------------------------ feedback
    def _press_feedback(self, _event=None) -> str:
        self.btn_feedback.invoke()
        return "break"

    def open_feedback(self) -> None:
        """The tool page's feedback box in the browser. Nothing is sent from here; when no
        browser opens, the address is shown so it can be copied."""
        self.tip_feedback.hide()
        url = update_check.feedback_url(UPDATE_SLUG, net.APP_VERSION, i18n.current_lang())
        try:
            opened = webbrowser.open(url)
        except Exception:  # webbrowser.Error, OSError, ...
            opened = False
        if not opened:
            self._show_feedback_address(url)

    def _show_feedback_address(self, url: str) -> None:
        p = self.px
        win = tk.Toplevel(self.root)
        win.title(t("feedback_failed_title"))
        win.transient(self.root)
        win.configure(bg=BG)
        win.resizable(False, False)
        frame = ttk.Frame(win, padding=p(14))
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text=t("feedback_failed"), wraplength=p(440), justify="left").grid(
            row=0, column=0, columnspan=3, sticky="w")
        var = tk.StringVar(value=url)
        entry = self._entry(frame, var)
        entry.configure(state="readonly", readonlybackground=CARD, width=60)
        entry.grid(row=1, column=0, sticky="ew", pady=(p(10), 0))

        def copy() -> None:
            try:
                win.clipboard_clear()
                win.clipboard_append(url)
                btn_copy.configure(text=t("btn_copied"))
            except tk.TclError:
                pass

        btn_copy = ttk.Button(frame, text=t("btn_copy"), command=copy)
        btn_copy.grid(row=1, column=1, padx=(p(8), 0), pady=(p(10), 0))
        ttk.Button(frame, text=t("btn_close"), command=win.destroy).grid(row=1, column=2, padx=(p(6), 0),
                                                                        pady=(p(10), 0))
        entry.select_range(0, "end")
        entry.focus_set()
        win.bind("<Escape>", lambda _e: win.destroy())
        self._feedback_win = win

    def _on_lyrics_toggle(self) -> None:
        first_time = self.var_lyrics.get() and not self.prefs.lyrics_notice_seen
        if first_time:
            self.prefs.lyrics_notice_seen = True
        self._save_prefs()
        self._update_lyrics_info()
        if first_time:
            self.show_lyrics_notice()

    def show_lyrics_notice(self) -> None:
        messagebox.showwarning(t("lyrics_notice_title"), t("lyrics_notice"), parent=self.root)

    def view_lyrics(self) -> None:
        s = self.current
        if s is None or not s.has_lyrics or self._busy():
            return
        try:
            text = tags.read_lyrics(s.path)
        except Exception:
            self._set_status("err_open_failed", name=s.name())
            return
        p = self.px
        win = tk.Toplevel(self.root)
        win.title(t("dlg_lyrics_title", name=s.name()))
        win.transient(self.root)
        win.configure(bg=BG)
        win.geometry(f"{p(480)}x{p(580)}")
        frame = ttk.Frame(win, padding=p(12))
        frame.pack(fill="both", expand=True)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        box = tk.Text(frame, wrap="word", bg=CARD, fg=TEXT, relief="flat", bd=0, highlightthickness=1,
                      highlightbackground=BORDER, font=self.font_body, padx=p(12), pady=p(10))
        sb = ttk.Scrollbar(frame, orient="vertical", command=box.yview)
        box.configure(yscrollcommand=sb.set)
        box.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        box.insert("1.0", text)
        box.configure(state="disabled")  # shown as it is in the file; edit it in another tool
        win.bind("<Escape>", lambda _e: win.destroy())
        win.focus_set()

    def _on_country(self, _event=None) -> None:
        self._country = self.var_country.get()
        self._save_prefs()

    def _on_lang(self, _event=None) -> None:
        name = self.var_lang.get()
        code = next((c for c, n in i18n.LANG_NAMES.items() if n == name), i18n.DEFAULT_LANG)
        i18n.set_lang(code)
        self._apply_texts()

    def _on_close(self) -> None:
        self._closing = True
        self.cancel_event.set()
        try:
            self._save_prefs()
        except Exception:
            pass
        self._close_when_idle()

    def _close_when_idle(self) -> None:
        if self._busy():
            self.root.after(100, self._close_when_idle)
            return
        self._thumb_pool.shutdown(wait=False, cancel_futures=True)
        self.covers.close()
        self.root.destroy()


def open_in_explorer(path: str) -> None:
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])


def launch(initial_files: list[str] | None = None) -> None:
    app = App(initial_files)
    app.root.mainloop()
