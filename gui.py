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
from search_itunes import COUNTRIES

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    _HAS_DND = True
except Exception:  # pragma: no cover - optional dependency
    _HAS_DND = False

COVER_PX = 240
THUMB_PX = 40
TOP_PANE_PX = 372
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
GOOD_FG = "#15803d"
FAIR_FG = "#b45309"


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

    def dirty(self) -> bool:
        return bool(self.changed_fields()) or self.cover_changed

    def current_tags(self) -> tags.Tags:
        return tags.Tags.from_dict(self.values)

    def name(self) -> str:
        return os.path.basename(self.path)

    def attach_info(self, info: tags.FileInfo) -> None:
        """Keep the tags, drop the cover bytes: they are re-read when shown or saved."""
        self.has_cover = info.cover is not None
        info.cover = None
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

        self.prefs = prefs_mod.load()
        self.files: list[FileState] = []
        self.current: FileState | None = None
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.thumb_thread: threading.Thread | None = None
        self.thumb_gen = 0
        self._thumbs: dict[str, ImageTk.PhotoImage] = {}
        self._thumb_misses: set[str] = set()  # URLs that returned nothing; not asked again
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
        self.var_rename = tk.BooleanVar(value=self.prefs.rename)
        self.var_save_alert = tk.BooleanVar(value=self.prefs.save_alert)
        self.var_query = tk.StringVar()
        self.var_fields = {f: tk.StringVar() for f in tags.FIELDS}

        self._style()
        self._build()
        self._apply_texts()
        self._show_file(None)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        threading.Thread(target=self._probe_online, daemon=True).start()
        if initial_files:
            self.root.after(100, lambda: self.add_paths(initial_files))

    # ------------------------------------------------------------ look
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
        self._reg(self.lbl_drop, "drop_hint").grid(row=0, column=1, sticky="w", padx=(p(16), 0))
        self._reg(ttk.Label(head, style="Muted.TLabel"), "country_label").grid(row=0, column=2, padx=(0, p(6)))
        self.cmb_country = ttk.Combobox(head, state="readonly", width=5, textvariable=self.var_country, values=list(COUNTRIES))
        self.cmb_country.grid(row=0, column=3, padx=(0, p(18)))
        self.cmb_country.bind("<<ComboboxSelected>>", self._on_country)
        self._reg(ttk.Label(head, style="Muted.TLabel"), "lbl_language").grid(row=0, column=4, padx=(0, p(6)))
        self.cmb_lang = ttk.Combobox(head, state="readonly", width=10, textvariable=self.var_lang,
                                     values=[i18n.LANG_NAMES[c] for c in i18n.LANGS])
        self.cmb_lang.grid(row=0, column=5)
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
        self.chk_rename = self._reg(ttk.Checkbutton(bar, variable=self.var_rename, command=self._save_prefs), "opt_rename")
        self.chk_rename.grid(row=0, column=4, padx=(p(20), 0))
        self.chk_alert = self._reg(ttk.Checkbutton(bar, variable=self.var_save_alert, command=self._save_prefs), "opt_save_alert")
        self.chk_alert.grid(row=0, column=5, sticky="w", padx=(p(12), 0))
        # progress and status get a row of their own so long messages are not cut off
        self.progress = ttk.Progressbar(bar, mode="determinate", length=p(220))
        self.progress.grid(row=1, column=0, columnspan=2, sticky="w", pady=(p(10), 0))
        self.lbl_status = ttk.Label(bar, anchor="w", style="Muted.TLabel")
        self.lbl_status.grid(row=1, column=2, columnspan=4, sticky="ew", padx=(p(10), 0), pady=(p(10), 0))
        self.lbl_mem = ttk.Label(bar, anchor="e", style="Small.TLabel")
        self.lbl_mem.grid(row=1, column=6, sticky="e", padx=(p(10), 0), pady=(p(10), 0))
        self.root.after(1000, self._tick_memory)

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
        self._update_file_info()
        if self._status_key:
            self._set_status(self._status_key, **self._status_kwargs)

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
                  self.btn_add, self.btn_add_dir, self.btn_clear, self.btn_cover):
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
        self.covers.close()
        self._show_file(None)
        self._refresh_list()

    def _refresh_list(self) -> None:
        show = len(self.files) > 1
        if show:
            self.frm_files.grid()
        else:
            self.frm_files.grid_remove()
        for i, s in enumerate(self.files):
            mark = CHECK if (s.confirmed or s.auto or s.saved) else " "
            self.lst_files.delete(i)
            self.lst_files.insert(i, f" {mark} {s.name()}")
            fg = DONE_FG if s.saved else AUTO_FG if (s.auto and not s.confirmed) else TEXT
            self.lst_files.itemconfig(i, foreground=fg)
        if self.current is not None and self.current in self.files:
            idx = self.files.index(self.current)
            self.lst_files.selection_clear(0, "end")
            self.lst_files.selection_set(idx)

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
            result = pipeline.search_text(s.query, self.var_country.get(), s.info.length,
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
                        cover = pipeline.fetch_cover(pick, on_wait=self._on_wait, cancel=self.cancel_event)
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
            return
        self.lbl_file_info.configure(text=t("lbl_file_info", name=s.name(), fmt=s.info.fmt,
                                            length=self._fmt_length(s.info.length), bitrate=s.info.bitrate))

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
        self._paint_fields()
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
        self.tree.delete(*self.tree.get_children())
        self.thumb_gen += 1
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
        if cands:
            self.tree.selection_set("0")
            self.tree.focus("0")
            self._start_thumbs(cands, self.thumb_gen)

    def _start_thumbs(self, cands: list[Candidate], gen: int) -> None:
        todo = [(i, c) for i, c in enumerate(cands)
                if c.thumb_url and c.thumb_url not in self._thumbs and c.thumb_url not in self._thumb_misses]
        if not todo:
            return

        def fetch(i: int, c: Candidate) -> None:
            if gen != self.thumb_gen or self._closing:
                return
            data = pipeline.fetch_thumb(c, cancel=self.cancel_event)
            if data:
                self._ui(self._set_thumb, gen, str(i), c.thumb_url, data)
            else:
                if len(self._thumb_misses) > 5000:
                    self._thumb_misses.clear()
                self._thumb_misses.add(c.thumb_url)

        def work() -> None:
            # top rows first, four at a time: Cover Art Archive answers via a slow redirect
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                for i, c in todo:
                    pool.submit(fetch, i, c)

        self.thumb_thread = threading.Thread(target=work, daemon=True)
        self.thumb_thread.start()

    def _set_thumb(self, gen: int, iid: str, url: str, data: bytes) -> None:
        try:
            with Image.open(io.BytesIO(data)) as im:
                im = im.convert("RGB")
                size = self.px(THUMB_PX)
                im.thumbnail((size, size), Image.LANCZOS)
                photo = ImageTk.PhotoImage(im)
        except Exception:
            return
        self._thumbs[url] = photo
        if len(self._thumbs) > 400:
            for key in list(self._thumbs)[:100]:
                del self._thumbs[key]
        if gen == self.thumb_gen and self.tree.exists(iid):
            self.tree.item(iid, image=photo)

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
        result = pipeline.search_text(query, self.var_country.get(), s.info.length,
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
        self._run(self._search_sound_job, s)

    def _search_sound_job(self, s: FileState) -> None:
        result = pipeline.search_sound(s.path, self.prefs, self.var_query.get().strip(), s.info.length,
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
        s.values = pipeline.apply_candidate(s.current_tags(), cand, overwrite).as_dict()
        s.saved = False

    def apply_selected(self) -> None:
        s = self.current
        cand = self._selected_candidate()
        if s is None or cand is None:
            self._set_status("msg_no_selection")
            return
        s.selected, s.auto, s.confirmed = cand, False, True
        self._apply_values(s, cand)
        self._show_file(s)
        if cand.cover_url:
            self._run(self._fetch_cover_job, s, cand)

    def _fetch_cover_job(self, s: FileState, cand: Candidate) -> None:
        data = pipeline.fetch_cover(cand, on_wait=self._on_wait, cancel=self.cancel_event)
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
        if not s.dirty():
            self._set_status("msg_nothing_to_save")
            return
        self._run(self._save_job, [s])

    def save_all(self) -> None:
        todo = [s for s in self.files if s.info is not None and s.dirty() and not s.saved]
        if not todo:
            self._set_status("msg_nothing_to_save")
            return
        self._run(self._save_job, todo)

    def _save_job(self, states: list[FileState]) -> None:
        saved = 0
        failed: list[str] = []
        cover_failed = 0
        last_backup = ""
        for idx, s in enumerate(states, 1):
            if self.cancel_event.is_set():
                break
            self._ui(self._set_status, "status_saving", index=idx, total=len(states), name=s.name())
            self._ui(self.progress.configure, {"value": 100.0 * (idx - 1) / len(states)})
            try:
                res = pipeline.save_file(s.path, s.current_tags(), s.load_cover() if s.cover_changed else None,
                                         self.prefs, rename=self.var_rename.get())
            except tags.FileLocked:
                failed.append(s.name())
                continue
            except Exception:
                failed.append(s.name())
                continue
            s.path = res.path
            s.attach_info(tags.read_file(s.path))
            s.cover_key, s.cover_changed = None, False
            s.saved, s.auto, s.confirmed = True, False, True
            last_backup = os.path.basename(res.backup)
            if res.cover_failed:
                cover_failed += 1
            saved += 1
        self._ui(self._save_done, saved, failed, cover_failed, last_backup)

    def _save_done(self, saved: int, failed: list[str], cover_failed: int, last_backup: str) -> None:
        self._refresh_list()
        if self.current is not None:
            self._show_file(self.current)
        lines = [t("msg_saved", count=saved)]
        if saved and last_backup:
            lines.append(t("msg_backup_note", file=last_backup))
        if cover_failed:
            lines.append(t("msg_cover_failed"))
        if failed:
            lines.append(t("err_readonly") + ": " + ", ".join(failed))
        self._set_status_text(" \u00b7 ".join(lines))
        if self._closing:
            return
        if failed:
            messagebox.showerror(t("dlg_error"), "\n".join(lines), parent=self.root)
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
        s.attach_info(tags.read_file(s.path))
        s.cover_key, s.cover_changed = None, False
        s.saved, s.auto, s.confirmed, s.selected = False, False, False, None
        self._ui(self._undo_done, s, exact)

    def _undo_done(self, s: FileState, exact: bool) -> None:
        if s is self.current:
            self._show_file(s)
        self._set_status("msg_restored_exact" if exact else "msg_restored_tags", name=s.name())

    # ------------------------------------------------------------ settings
    def _save_prefs(self) -> None:
        self.prefs.rename = bool(self.var_rename.get())
        self.prefs.save_alert = bool(self.var_save_alert.get())
        self.prefs.country = self.var_country.get()
        prefs_mod.save(self.prefs)

    def _on_country(self, _event=None) -> None:
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
        self.covers.close()
        self.root.destroy()


def open_in_explorer(path: str) -> None:
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])


def launch(initial_files: list[str] | None = None) -> None:
    app = App(initial_files)
    app.root.mainloop()
