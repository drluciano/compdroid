"""CompDroid desktop window (Tkinter, ships with Python on Windows).

Launch with `compdroid-gui`, `compdroid gui`, or `pyw -m compdroid.gui`.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__, api
from .dump import Dump, DumpError, open_dump
from .profiles import ProfileError, default_profiles_dir
from .settings import (ANTI_ALIASING, ASPECT, DRIVERS, FPS_TARGETS, FRAME_GEN, UPSCALERS, GameSettings,
                       default_output_dir, settings_path)

BG = "#16181d"
PANEL = "#1f2229"
FIELD = "#2a2e37"
TEXT = "#e6e8ec"
MUTED = "#9aa1ad"
ACCENT = "#4fb3a9"
WARN = "#e0b354"
ERR = "#e06c6c"

STATUS_COLORS = {"playable": ACCENT, "ingame": ACCENT, "boots": WARN, "untested": MUTED, "broken": ERR}


def _style(root: tk.Tk) -> None:
    s = ttk.Style(root)
    s.theme_use("clam")
    root.configure(bg=BG)
    s.configure(".", background=BG, foreground=TEXT, fieldbackground=FIELD, bordercolor=PANEL,
                lightcolor=PANEL, darkcolor=PANEL, troughcolor=PANEL, font=("Segoe UI", 10))
    s.configure("TFrame", background=BG)
    s.configure("Panel.TFrame", background=PANEL)
    s.configure("TLabel", background=BG, foreground=TEXT)
    s.configure("Panel.TLabel", background=PANEL)
    s.configure("Muted.TLabel", background=BG, foreground=MUTED)
    s.configure("PanelMuted.TLabel", background=PANEL, foreground=MUTED)
    s.configure("Title.TLabel", font=("Segoe UI Semibold", 18))
    s.configure("H2.TLabel", background=PANEL, font=("Segoe UI Semibold", 12))
    s.configure("Value.TLabel", background=PANEL, font=("Segoe UI Semibold", 10))
    s.configure("TButton", background=FIELD, foreground=TEXT, padding=(12, 6), borderwidth=0)
    s.map("TButton", background=[("disabled", PANEL), ("active", "#353a45")],
          foreground=[("disabled", "#5c6370")])
    s.configure("Accent.TButton", background=ACCENT, foreground="#0e1a19")
    s.map("Accent.TButton", background=[("disabled", PANEL), ("active", "#63c7bd")])
    s.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, insertcolor=TEXT, padding=6)
    s.configure("TCombobox", fieldbackground=FIELD, background=FIELD, foreground=TEXT, arrowcolor=TEXT, padding=4)
    s.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", TEXT)])
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    s.configure("TCheckbutton", background=PANEL, foreground=TEXT)
    s.map("TCheckbutton", background=[("active", PANEL)])
    s.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 4, 0, 0))
    s.configure("TNotebook.Tab", background=BG, foreground=MUTED, padding=(14, 7), borderwidth=0)
    s.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", TEXT)])
    s.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=26, borderwidth=0)
    s.configure("Treeview.Heading", background=FIELD, foreground=MUTED, relief="flat", padding=4)
    s.map("Treeview", background=[("selected", "#2f4a48")])
    s.configure("Horizontal.TScale", background=ACCENT, troughcolor=FIELD, bordercolor=PANEL,
                lightcolor=ACCENT, darkcolor=ACCENT, sliderlength=18)


class App:
    def __init__(self, root: tk.Tk, profiles_dir: str | None = None):
        self.root = root
        self.profiles_dir = profiles_dir or str(default_profiles_dir())
        self.dump: Dump | None = None
        self.info: dict | None = None
        self.scan_result: list[dict] | None = None
        self.settings = GameSettings()
        self._q: queue.Queue = queue.Queue()

        root.title("CompDroid")
        root.geometry("1040x700")
        root.minsize(860, 560)
        _style(root)

        self.dump_var = tk.StringVar()
        self.out_var = tk.StringVar(value=str(default_output_dir()))
        self.status_var = tk.StringVar(value="Pick the folder that holds your game's extracted exefs and romfs.")

        self._build_header()
        self._build_picker()
        body = ttk.Frame(root)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        self._build_game_card(body)
        self._build_tabs(body)
        ttk.Label(root, textvariable=self.status_var, style="Muted.TLabel").pack(fill="x", padx=16, pady=(0, 10))
        root.after(80, self._poll)

    # ---------- layout ----------
    def _build_header(self) -> None:
        f = ttk.Frame(self.root)
        f.pack(fill="x", padx=16, pady=(14, 6))
        ttk.Label(f, text="CompDroid", style="Title.TLabel").pack(side="left")
        ttk.Label(f, text=f"  v{__version__}  ·  your Switch game, native on Android. No emulation.",
                  style="Muted.TLabel").pack(side="left", pady=(6, 0))

    def _build_picker(self) -> None:
        f = ttk.Frame(self.root)
        f.pack(fill="x", padx=16, pady=(4, 12))
        ttk.Label(f, text="Game folder").pack(side="left", padx=(0, 8))
        e = ttk.Entry(f, textvariable=self.dump_var)
        e.pack(side="left", fill="x", expand=True)
        e.bind("<Return>", lambda _e: self.inspect())
        ttk.Button(f, text="Browse…", command=self.browse).pack(side="left", padx=(8, 0))
        self.inspect_btn = ttk.Button(f, text="Inspect", style="Accent.TButton", command=self.inspect)
        self.inspect_btn.pack(side="left", padx=(8, 0))

    def _build_game_card(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Panel.TFrame", padding=16)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        card.configure(width=280)
        card.grid_propagate(False)
        card.columnconfigure(0, weight=1)
        self.card_title = ttk.Label(card, text="No game loaded", style="H2.TLabel", wraplength=248)
        self.card_title.grid(row=0, column=0, sticky="w")
        self.card_rows: dict[str, ttk.Label] = {}
        for i, key in enumerate(["Title ID", "Profile", "Version", "Status", "RomFS", "Code modules",
                                 "Rewrite sites", "16 KB pages"], start=1):
            ttk.Label(card, text=key, style="PanelMuted.TLabel").grid(row=i * 2 - 1, column=0, sticky="w",
                                                                       pady=(10, 0))
            v = ttk.Label(card, text="–", style="Value.TLabel", wraplength=248)
            v.grid(row=i * 2, column=0, sticky="w")
            self.card_rows[key] = v
        ttk.Label(card, text="Only extracted folders are read. NSP/XCI files and keys are refused.",
                  style="PanelMuted.TLabel", wraplength=248).grid(row=40, column=0, sticky="sw", pady=(18, 0))
        card.rowconfigure(39, weight=1)

    def _build_tabs(self, parent: ttk.Frame) -> None:
        nb = ttk.Notebook(parent)
        nb.grid(row=0, column=1, sticky="nsew")
        self.nb = nb

        # Modules
        f = ttk.Frame(nb, style="Panel.TFrame", padding=12)
        self.mod_tree = self._tree(f, ("module", "build", "text", "ro", "data"),
                                   ("Module", "Build ID", ".text", ".rodata", ".data"), (90, 330, 80, 80, 80))
        nb.add(f, text="Modules")

        # Native scan
        f = ttk.Frame(nb, style="Panel.TFrame", padding=12)
        top = ttk.Frame(f, style="Panel.TFrame")
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Instructions native mode rewrites. Everything else runs unchanged on the phone's CPU.",
                  style="PanelMuted.TLabel").pack(side="left")
        self.scan_btn = ttk.Button(top, text="Run scan", command=self.scan, state="disabled")
        self.scan_btn.pack(side="right")
        self.scan_tree = self._tree(f, ("module", "item", "count", "note"), ("Module", "Instruction", "Count", "Why"),
                                    (80, 240, 70, 380))
        nb.add(f, text="Native scan")

        # In-game defaults
        f = ttk.Frame(nb, style="Panel.TFrame", padding=16)
        self._build_settings(f)
        nb.add(f, text="In-game settings")

        # Build
        f = ttk.Frame(nb, style="Panel.TFrame", padding=16)
        self._build_build(f)
        nb.add(f, text="Build APK")

        # Log
        f = ttk.Frame(nb, style="Panel.TFrame", padding=12)
        self.log = tk.Text(f, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief="flat", wrap="word",
                           font=("Consolas", 9), height=10)
        self.log.pack(fill="both", expand=True)
        nb.add(f, text="Log")

    def _tree(self, parent, cols, heads, widths) -> ttk.Treeview:
        t = ttk.Treeview(parent, columns=cols, show="headings", selectmode="browse")
        for c, h, w in zip(cols, heads, widths):
            t.heading(c, text=h, anchor="w")
            t.column(c, width=w, anchor="w", stretch=c in ("build", "note"))
        sb = ttk.Scrollbar(parent, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        t.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return t

    def _build_settings(self, f: ttk.Frame) -> None:
        ttk.Label(f, text="Defaults for a fresh install", style="H2.TLabel").grid(row=0, column=0, columnspan=3,
                                                                                 sticky="w")
        ttk.Label(f, text="Everything here can still be changed on the phone from the in-game menu.",
                  style="PanelMuted.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 12))
        self.svars: dict[str, tk.Variable] = {}
        rows = [
            ("Vulkan driver", "driver", DRIVERS),
            ("Target FPS", "target_fps", FPS_TARGETS),
            ("Upscaler", "upscaler", UPSCALERS),
            ("Frame generation", "frame_generation", FRAME_GEN),
            ("Anti-aliasing", "anti_aliasing", ANTI_ALIASING),
            ("Aspect ratio", "aspect_ratio", ASPECT),
        ]
        r = 2
        for label, key, options in rows:
            ttk.Label(f, text=label, style="Panel.TLabel").grid(row=r, column=0, sticky="w", pady=5, padx=(0, 16))
            v = tk.StringVar(value=getattr(self.settings, key))
            cb = ttk.Combobox(f, textvariable=v, values=options, state="readonly", width=26)
            cb.grid(row=r, column=1, sticky="w")
            self.svars[key] = v
            if key == "driver":
                cb.bind("<<ComboboxSelected>>", lambda _e: self._driver_changed())
                self.driver_btn = ttk.Button(f, text="Choose zip…", command=self._pick_driver)
                self.driver_btn.grid(row=r, column=2, sticky="w", padx=(8, 0))
                r += 1
                self.svars["driver_zip"] = tk.StringVar(value="")
                ttk.Label(f, textvariable=self.svars["driver_zip"], style="PanelMuted.TLabel").grid(
                    row=r, column=1, columnspan=2, sticky="w")
            r += 1

        ttk.Label(f, text="Internal resolution", style="Panel.TLabel").grid(row=r, column=0, sticky="w", pady=5)
        self.svars["resolution_scale"] = tk.IntVar(value=self.settings.resolution_scale)
        res_lbl = ttk.Label(f, text="100%", style="Value.TLabel", width=6)
        scale = ttk.Scale(f, from_=25, to=200, orient="horizontal", length=200,
                          command=lambda v: (self.svars["resolution_scale"].set(int(float(v)) // 5 * 5),
                                             res_lbl.configure(text=f"{self.svars['resolution_scale'].get()}%")))
        scale.set(self.settings.resolution_scale)
        scale.grid(row=r, column=1, sticky="w")
        res_lbl.grid(row=r, column=2, sticky="w", padx=(8, 0))
        r += 1
        for label, key in (("Dynamic resolution toward the FPS target", "dynamic_resolution"),
                           ("Show performance overlay", "show_overlay")):
            v = tk.BooleanVar(value=getattr(self.settings, key))
            ttk.Checkbutton(f, text=label, variable=v).grid(row=r, column=1, columnspan=2, sticky="w", pady=4)
            self.svars[key] = v
            r += 1
        ttk.Label(f, text="Turnip is for Adreno GPUs. Frame generation works best from a steady 30 or 60.",
                  style="PanelMuted.TLabel").grid(row=r, column=0, columnspan=3, sticky="w", pady=(10, 0))
        r += 1
        self.save_settings_btn = ttk.Button(f, text="Save defaults", style="Accent.TButton",
                                            command=self.save_settings, state="disabled")
        self.save_settings_btn.grid(row=r, column=0, sticky="w", pady=(16, 0))
        self._driver_changed()

    def _build_build(self, f: ttk.Frame) -> None:
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="Package the game as an APK", style="H2.TLabel").grid(row=0, column=0, columnspan=3,
                                                                               sticky="w")
        ttk.Label(f, text="Builds go to a folder outside this repo. They contain your game's code: keep them "
                          "on your own devices.", style="PanelMuted.TLabel", wraplength=640).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(0, 12))
        ttk.Label(f, text="Output folder", style="Panel.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 12))
        ttk.Entry(f, textvariable=self.out_var).grid(row=2, column=1, sticky="ew")
        ttk.Button(f, text="Browse…", command=self._pick_out).grid(row=2, column=2, padx=(8, 0))
        ttk.Label(f, text="Package name", style="Panel.TLabel").grid(row=3, column=0, sticky="w", pady=(10, 0))
        self.pkg_lbl = ttk.Label(f, text="–", style="Value.TLabel")
        self.pkg_lbl.grid(row=3, column=1, sticky="w", pady=(10, 0))

        steps = ttk.Frame(f, style="Panel.TFrame")
        steps.grid(row=4, column=0, columnspan=3, sticky="w", pady=(18, 0))
        for i, s in enumerate(["Apply profile patches and native rewrites", "Inject into the runtime template APK",
                               "Zipalign and sign with your local key", "Install over adb and copy RomFS"], 1):
            ttk.Label(steps, text=f"{i}.  {s}", style="PanelMuted.TLabel").pack(anchor="w", pady=1)

        btns = ttk.Frame(f, style="Panel.TFrame")
        btns.grid(row=5, column=0, columnspan=3, sticky="w", pady=(18, 0))
        ttk.Button(btns, text="Build APK", style="Accent.TButton", state="disabled").pack(side="left")
        ttk.Button(btns, text="Install on phone (adb)", state="disabled").pack(side="left", padx=(8, 0))
        ttk.Label(f, text="Building arrives with milestone M1 (runtime template APK).", style="PanelMuted.TLabel"
                  ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(8, 0))

    # ---------- actions ----------
    def browse(self) -> None:
        d = filedialog.askdirectory(title="Folder with your extracted exefs and romfs")
        if d:
            self.dump_var.set(d)
            self.inspect()

    def inspect(self) -> None:
        path = self.dump_var.get().strip()
        if not path:
            self.browse()
            return
        self._busy(f"Reading {path}…")

        def work():
            dump = open_dump(path)
            return dump, api.inspect(dump, self.profiles_dir)

        self._run(work, self._inspected)

    def _inspected(self, result) -> None:
        self.dump, self.info = result
        info = self.info
        self.scan_result = None
        prof = info["profile"]
        self.card_title.configure(text=prof["name"] if prof else (info["npdm_name"] or "Unknown game"))
        self._card("Title ID", info["title_id"])
        if prof is None:
            self._card("Profile", "None yet: generic best effort", MUTED)
            self._card("Version", "–")
            self._card("Status", "untested", MUTED)
        else:
            self._card("Profile", Path(prof["file"]).name)
            self._card("Version", prof["version"] or "Build not listed in profile", None if prof["version"] else WARN)
            self._card("Status", prof["status"], STATUS_COLORS.get(prof["status"], WARN))
        rf = info["romfs"]
        self._card("RomFS", "Not found next to exefs" if rf is None else
                   f"{api.human(rf['bytes'])}, {rf['files']} files" if rf["kind"] == "dir" else
                   f"romfs.bin, {api.human(rf['bytes'])}", ERR if rf is None else None)
        self._card("Code modules", ", ".join(info["modules"]))
        self._card("Rewrite sites", "Run the native scan")
        self._card("16 KB pages", "–")
        self.mod_tree.delete(*self.mod_tree.get_children())
        for name, m in info["modules"].items():
            self.mod_tree.insert("", "end", values=(name, m["build_id"], api.human(m["text"]), api.human(m["ro"]),
                                                    api.human(m["data"])))
        self.pkg_lbl.configure(text=f"dev.compdroid.t{info['title_id'].lower()}")
        self.settings = GameSettings.load(settings_path(Path(self.out_var.get()), info["title_id"]))
        self._settings_to_ui()
        self.scan_btn.configure(state="normal")
        self.save_settings_btn.configure(state="normal")
        self._log(f"Inspected {info['root']}: {info['title_id']} ({len(info['modules'])} modules)")
        self._idle("Loaded. Run the native scan to see what the rewriter has to patch.")
        self.scan()

    def scan(self) -> None:
        if self.dump is None:
            return
        self.scan_btn.configure(state="disabled")
        self._busy("Scanning game code…")
        self._run(lambda: api.scan(self.dump), self._scanned)

    def _scanned(self, results: list[dict]) -> None:
        self.scan_result = results
        t = self.scan_tree
        t.delete(*t.get_children())
        total = 0
        issues = 0
        for r in results:
            total += r["rewrite_sites"]
            for num, count in r["svc"].items():
                t.insert("", "end", values=(r["module"], f"svc {num}  {api.svc_name(num)}", count,
                                            "Horizon system call, answered by the host kernel"))
            for reg, count in r["sysreg"].items():
                t.insert("", "end", values=(r["module"], reg, count, api.SYSREG_NOTES[reg]))
            for issue in r["page16k_issues"]:
                issues += 1
                t.insert("", "end", values=(r["module"], "16 KB page", "", issue))
        self._card("Rewrite sites", f"{total:,} across {len(results)} modules")
        self._card("16 KB pages", "All segments aligned" if issues == 0 else f"{issues} shared page(s), loader merges",
                   ACCENT if issues == 0 else WARN)
        self.scan_btn.configure(state="normal")
        self._log(f"Scan: {total} rewrite sites, {issues} 16 KB page issue(s)")
        self._idle("Scan done.")

    def save_settings(self) -> None:
        if not self.info:
            return
        s = self._ui_to_settings()
        errs = s.validate()
        if errs:
            messagebox.showwarning("CompDroid", "\n".join(errs))
            return
        p = settings_path(Path(self.out_var.get()), self.info["title_id"])
        s.save(p)
        self.settings = s
        self._log(f"Saved defaults to {p}")
        self._idle(f"Saved in-game defaults to {p}")

    # ---------- helpers ----------
    def _settings_to_ui(self) -> None:
        for k, v in self.svars.items():
            v.set(getattr(self.settings, k))
        self._driver_changed()

    def _ui_to_settings(self) -> GameSettings:
        vals = {k: v.get() for k, v in self.svars.items()}
        return GameSettings(**vals)

    def _driver_changed(self) -> None:
        custom = self.svars["driver"].get() == "Custom driver (zip)"
        self.driver_btn.configure(state="normal" if custom else "disabled")
        if not custom:
            self.svars["driver_zip"].set("")

    def _pick_driver(self) -> None:
        p = filedialog.askopenfilename(title="Vulkan driver package (e.g. Mesa Turnip)",
                                       filetypes=[("Driver package", "*.zip"), ("All files", "*.*")])
        if p:
            self.svars["driver_zip"].set(p)

    def _pick_out(self) -> None:
        d = filedialog.askdirectory(title="Where to put builds")
        if d:
            self.out_var.set(d)

    def _card(self, key: str, text: str, color: str | None = None) -> None:
        self.card_rows[key].configure(text=text, foreground=color or TEXT)

    def _log(self, line: str) -> None:
        self.log.insert("end", line + "\n")
        self.log.see("end")

    def _busy(self, msg: str) -> None:
        self.status_var.set(msg)
        self.inspect_btn.configure(state="disabled")
        self.root.configure(cursor="watch")

    def _idle(self, msg: str) -> None:
        self.status_var.set(msg)
        self.inspect_btn.configure(state="normal")
        self.root.configure(cursor="")

    def _run(self, fn, on_done) -> None:
        def worker():
            try:
                self._q.put((on_done, fn(), None))
            except Exception as e:  # noqa: BLE001 - shown to the user
                self._q.put((on_done, None, e))

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self) -> None:
        try:
            while True:
                on_done, result, err = self._q.get_nowait()
                if err is None:
                    on_done(result)
                else:
                    msg = str(err) if isinstance(err, (DumpError, ProfileError)) else \
                        "".join(traceback.format_exception(err))
                    self._log(f"Error: {msg}")
                    self.scan_btn.configure(state="normal" if self.dump else "disabled")
                    self._idle(f"Error: {str(err).splitlines()[0] if str(err) else type(err).__name__}")
                    messagebox.showerror("CompDroid", str(err))
        except queue.Empty:
            pass
        self.root.after(80, self._poll)


def run(initial_dump: str | None = None, profiles_dir: str | None = None) -> None:
    try:  # sharp text on high-DPI Windows displays
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - not Windows
        pass
    root = tk.Tk()
    app = App(root, profiles_dir)
    if initial_dump:
        app.dump_var.set(initial_dump)
        root.after(200, app.inspect)
    root.mainloop()


def main() -> None:
    import sys

    run(sys.argv[1] if len(sys.argv) > 1 else None)


if __name__ == "__main__":
    main()
