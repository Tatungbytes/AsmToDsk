#!/usr/bin/env python3
# TatungBytes_Tool.py
# Z80 .asm -> CP/M .COM -> Tatung Einstein .DSK, plus one click Run in MAME.

APP_NAME = "TatungBytes Toolkit"
APP_VERSION = "1.4.8"
APP_TITLE = f"{APP_NAME} v{APP_VERSION}"

import os
import shutil
import subprocess
import threading
from pathlib import Path
import sys
import datetime
import json
import tkinter as tk

# Theming
try:
    import ttkbootstrap as tb
    from ttkbootstrap.constants import *
    from tkinter import ttk, filedialog, messagebox
    THEME = True
except Exception:
    from tkinter import ttk, filedialog, messagebox
    THEME = False

from tkinter import font as tkfont

DEFAULT_ORIGIN = "256"
DEFAULT_FMT = "einstein"
DEFAULT_RESOLUTION = "800x600"

# ------------------------------------------------------------
# Local Windows Defaults (tools next to this script)
# ------------------------------------------------------------

BASE = Path(__file__).resolve().parent

HARDCODED = {
    "z80asm": str(BASE / "z88dk" / "bin" / "z80asm.exe"),
    "appmake": str(BASE / "z88dk" / "bin" / "z88dk-appmake.exe"),
    "workdir": str(BASE),                          # working folder = script folder
    "mame": str(BASE / "mame" / "mame.exe"),       # mame.exe (not mame64.exe)
    "system_dsk": str(BASE / "DOS80.DSK"),         # DOS80.DSK next to script
    "rompath": str(BASE / "mame" / "roms"),
}

LOG_DIR = BASE / "Logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

CONFIG_PATH = BASE / "config.json"


def default_config():
    """Base default configuration."""
    return {
        "z80asm": HARDCODED["z80asm"],
        "appmake": HARDCODED["appmake"],
        "workdir": HARDCODED["workdir"],
        "mame": HARDCODED["mame"],
        "system_dsk": HARDCODED["system_dsk"],
        "rompath": HARDCODED["rompath"],
        "origin": DEFAULT_ORIGIN,
        "cpmdisk_fmt": DEFAULT_FMT,
        "video_soft": True,
        "windowed": True,
        "resolution": DEFAULT_RESOLUTION,
        "ui_active": True,
        "skip_intro": True,
    }


def load_config():
    """Load config.json if present, otherwise return defaults."""
    cfg = default_config()
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg.update(data)
        except Exception:
            # Ignore broken config file and fall back to defaults
            pass
    return cfg


def which(cmd):
    return shutil.which(cmd)


class FileLogger:
    """Simple logfile writer and process runner."""
    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        header = f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {APP_TITLE}\n"
        self._write(header)

    def _write(self, text: str):
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(text)

    def line(self, text: str):
        self._write(text if text.endswith("\n") else text + "\n")

    def cmd(self, args):
        self.line(f"$ {' '.join(args)}")

    def stream_proc(self, args, cwd=None, env=None):
        """
        Run a process, stream output to log, and return (rc, full_output_text).
        Does not raise — caller checks rc.
        """
        self.cmd(args)
        try:
            proc = subprocess.Popen(
                args,
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                shell=False,
            )
        except Exception as e:
            # Process could not start (missing exe, etc.)
            msg = f"Failed to start process: {e}\n"
            self._write(msg)
            return 1, msg

        lines = []
        for line in proc.stdout:
            self._write(line)
            lines.append(line)
        rc = proc.wait()
        return rc, "".join(lines)


def _remove_com_variants(folder: Path, base_stem: str):
    """Delete any file whose case-insensitive name matches <base>.com in a folder."""
    wanted_lower = f"{base_stem.lower()}.com"
    try:
        for p in folder.iterdir():
            if p.is_file() and p.name.lower() == wanted_lower:
                p.unlink()
    except FileNotFoundError:
        pass


def _normalise_to_single_uppercase_com(wd: Path, asm_dir: Path, base_stem: str) -> Path:
    """
    Guarantee exactly one COM named UPPERCASE.COM in the working dir.
    Collect every path in wd and asm_dir whose name casefolds to base_stem.com,
    move the newest one to wd/UPPERCASE.COM, delete the rest.
    """
    wanted_lower = f"{base_stem.lower()}.com"
    candidates = []

    for folder in {wd, asm_dir}:
        if folder and folder.exists():
            for p in folder.iterdir():
                if p.is_file() and p.name.lower() == wanted_lower:
                    candidates.append(p)

    desired = wd / f"{base_stem}.COM"
    keep = None

    if desired in candidates:
        keep = desired
    elif candidates:
        keep = max(candidates, key=lambda p: p.stat().st_mtime)

    if keep:
        if keep != desired:
            try:
                keep.replace(desired)
            except Exception:
                shutil.move(str(keep), str(desired))

    for p in candidates:
        if p.exists() and p != desired:
            try:
                p.unlink()
            except Exception:
                pass

    return desired


class App:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.resizable(True, True)

        # Load config
        self.config = load_config()

        # Vars, all prepopulated from config (which falls back to defaults)
        self.var_z80asm = tk.StringVar(value=self.config["z80asm"])
        self.var_appmake = tk.StringVar(value=self.config["appmake"])

        self.var_asm = tk.StringVar()
        self.var_workdir = tk.StringVar(value=self.config["workdir"])
        self.var_origin = tk.StringVar(value=self.config["origin"])  # info only
        self.var_cpmdisk_fmt = tk.StringVar(value=self.config["cpmdisk_fmt"])

        self.var_mame = tk.StringVar(value=self.config["mame"])
        self.var_dos80 = tk.StringVar(value=self.config["system_dsk"])
        self.var_rompath = tk.StringVar(value=self.config["rompath"])
        self.var_video_soft = tk.BooleanVar(value=bool(self.config["video_soft"]))
        self.var_windowed = tk.BooleanVar(value=bool(self.config["windowed"]))
        self.var_resolution = tk.StringVar(value=self.config["resolution"])
        self.var_ui_active = tk.BooleanVar(value=bool(self.config["ui_active"]))
        self.var_skip_intro = tk.BooleanVar(value=bool(self.config["skip_intro"]))

        # derived
        self.base_upper = ""     # set from ASM filename
        self.last_log_path = None

        # when ASM changes, recompute base
        self.var_asm.trace_add("write", self._on_asm_changed)

        self._build_ui()
        self._fit_to_content()

    # ---- Env helper for bundled Z88DK ----

    def _make_env_with_z88dk(self):
        env = os.environ.copy()
        z88dk_dir = BASE / "z88dk"
        cfg_dir = z88dk_dir / "lib" / "config"
        if z88dk_dir.is_dir():
            env.setdefault("Z88DK", str(z88dk_dir))
        if cfg_dir.is_dir():
            env.setdefault("ZCCCFG", str(cfg_dir))
        return env

    # ---- Config save ----

    def _save_config(self):
        cfg = {
            "z80asm": self.var_z80asm.get().strip(),
            "appmake": self.var_appmake.get().strip(),
            "workdir": self.var_workdir.get().strip(),
            "mame": self.var_mame.get().strip(),
            "system_dsk": self.var_dos80.get().strip(),
            "rompath": self.var_rompath.get().strip(),
            "origin": self.var_origin.get().strip(),
            "cpmdisk_fmt": self.var_cpmdisk_fmt.get().strip(),
            "video_soft": bool(self.var_video_soft.get()),
            "windowed": bool(self.var_windowed.get()),
            "resolution": self.var_resolution.get().strip(),
            "ui_active": bool(self.var_ui_active.get()),
            "skip_intro": bool(self.var_skip_intro.get()),
        }
        try:
            with CONFIG_PATH.open("w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, sort_keys=True)
        except Exception:
            # If saving fails, we don't kill the app
            pass

    def on_close(self):
        self._save_config()
        self.root.destroy()

    # UI
    def _build_ui(self):
        pad = 8

        # Fonts for emphasis
        default_font = tkfont.nametofont("TkDefaultFont")
        emphasised_font = default_font.copy()
        emphasised_font.configure(weight="bold")

        # Root content frame
        frm = ttk.Frame(self.root, padding=10)
        frm.pack(fill="both", expand=True)

        # Project
        lf_proj = ttk.LabelFrame(frm, text="Project")
        lf_proj.pack(fill="x", pady=(0, pad))
        self._row(
            lf_proj,
            "Source .asm:",
            self.var_asm,
            browse=True,
            filetypes=[("Assembly", "*.asm *.ASM"), ("All files", "*.*")],
            label_font=emphasised_font,
        )
        self._row(lf_proj, "Working folder:", self.var_workdir, browse_dir=True)

        # Tools
        lf_tools = ttk.LabelFrame(frm, text="Tools")
        lf_tools.pack(fill="x", pady=(0, pad))
        self._row(lf_tools, "z80asm:", self.var_z80asm, browse=True)
        self._row(lf_tools, "z88dk-appmake:", self.var_appmake, browse=True)

        # Build options
        lf_opts = ttk.LabelFrame(frm, text="Build options")
        lf_opts.pack(fill="x", pady=(0, pad))
        self._row(lf_opts, "Origin (info):", self.var_origin)
        self._row(lf_opts, "CP, M disk format:", self.var_cpmdisk_fmt)

        # MAME
        lf_mame = ttk.LabelFrame(frm, text="Run in MAME")
        lf_mame.pack(fill="x", pady=(0, pad))
        self._row(lf_mame, "mame:", self.var_mame, browse=True)
        self._row(
            lf_mame,
            "System Disk:",
            self.var_dos80,
            browse=True,
            filetypes=[("Disk images", "*.dsk *.DSK"), ("All files", "*.*")],
        )
        self._row(lf_mame, "ROM path:", self.var_rompath, browse_dir=True)

        toggles = ttk.Frame(lf_mame)
        toggles.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Checkbutton(
            toggles,
            text="Force software video",
            variable=self.var_video_soft,
        ).pack(side="left", padx=(0, 20))
        ttk.Checkbutton(
            toggles,
            text="Run in window",
            variable=self.var_windowed,
        ).pack(side="left", padx=(0, 20))
        ttk.Checkbutton(
            toggles,
            text="Enable MAME UI (Tab menu, Esc quit)",
            variable=self.var_ui_active,
        ).pack(side="left", padx=(0, 20))
        ttk.Checkbutton(
            toggles,
            text="Skip MAME intro screen",
            variable=self.var_skip_intro,
        ).pack(side="left")

        resrow = ttk.Frame(lf_mame)
        resrow.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Label(resrow, text="Resolution:").pack(side="left")
        res_values = [
            "640x480",
            "800x600",
            "1024x768",
            "1280x720",
            "1280x800",
            "1366x768",
            "1600x900",
            "1920x1080",
            "2560x1440",
        ]
        res_combo = ttk.Combobox(
            resrow,
            textvariable=self.var_resolution,
            values=res_values,
            width=12,
            state="readonly",
        )
        res_combo.pack(side="left", padx=8)

        # Actions
        actions = ttk.Frame(frm)
        actions.pack(fill="x", pady=(0, pad))
        style = "success.TButton" if THEME else None
        self.btn_build = ttk.Button(
            actions, text="Build COM + DSK", command=self._start_build, style=style
        )
        self.btn_build.pack(side="left")
        ttk.Button(actions, text="Run in MAME", command=self._start_run).pack(
            side="left", padx=10
        )
        ttk.Button(actions, text="Clean outputs", command=self._clean_outputs).pack(
            side="left", padx=10
        )

        # Status
        self.status = tk.StringVar(value="Ready")
        self.status2 = tk.StringVar(value="")
        ttk.Label(frm, textvariable=self.status, anchor="w").pack(fill="x")
        ttk.Label(frm, textvariable=self.status2, anchor="w", foreground="#666").pack(
            fill="x"
        )

    def _fit_to_content(self):
        """Size the toplevel to exactly fit the content, capped to screen."""
        self.root.update_idletasks()
        req_w = self.root.winfo_reqwidth()
        req_h = self.root.winfo_reqheight()
        margin = 120
        scr_w = self.root.winfo_screenwidth()
        scr_h = self.root.winfo_screenheight()
        width = min(req_w, scr_w - margin)
        height = min(req_h, scr_h - margin)
        self.root.minsize(width, height)
        x = (scr_w - width) // 2
        y = (scr_h - height) // 2
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _row(
        self,
        parent,
        label,
        var,
        browse: bool = False,
        browse_dir: bool = False,
        filetypes=None,
        label_font=None,
    ):
        row = ttk.Frame(parent)
        row.pack(fill="x", padx=6, pady=4)
        lbl = ttk.Label(row, text=label, width=18, anchor="e")
        if label_font is not None:
            lbl.configure(font=label_font)
        lbl.pack(side="left")
        entry = ttk.Entry(row, textvariable=var)
        entry.pack(side="left", fill="x", expand=True, padx=6)
        if browse:
            ttk.Button(
                row,
                text="Browse",
                command=lambda: self._browse_file(var, filetypes),
            ).pack(side="left")
        if browse_dir:
            ttk.Button(
                row,
                text="Choose",
                command=lambda: self._browse_dir(var),
            ).pack(side="left")

    # Helpers
    def _on_asm_changed(self, *_):
        p = self.var_asm.get().strip()
        self.base_upper = Path(p).stem.upper() if p else ""
        if self.base_upper:
            existing = self.status2.get()
            self.status2.set(f"Output base: {self.base_upper}    {existing}")

    def _browse_file(self, var, filetypes=None):
        path = filedialog.askopenfilename(
            title="Choose file",
            filetypes=filetypes or [("All files", "*.*")],
        )
        if path:
            var.set(path)

    def _browse_dir(self, var):
        d = filedialog.askdirectory(title="Choose folder")
        if d:
            var.set(d)

    def _out_paths(self):
        wd = Path(self.var_workdir.get())
        if not wd.exists():
            wd.mkdir(parents=True, exist_ok=True)
        base = self.base_upper or (
            Path(self.var_asm.get()).stem.upper() if self.var_asm.get() else "OUTPUT"
        )
        com = wd / f"{base}.COM"
        dsk = wd / f"{base}.dsk"
        obj = wd / f"{Path(self.var_asm.get()).stem}.o"
        log = LOG_DIR / f"{base}_build.log"
        return wd, base, com, dsk, obj, log

    # ---- Error window (scrollable) ----

    def _show_error_window(self, title: str, message: str):
        win = tk.Toplevel(self.root)
        win.title(title)
        win.geometry("800x500")
        win.transient(self.root)

        frame = ttk.Frame(win, padding=10)
        frame.pack(fill="both", expand=True)

        txt = tk.Text(frame, wrap="word")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=scroll.set)

        txt.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        if not message.endswith("\n"):
            message = message + "\n"
        txt.insert("1.0", message)
        txt.configure(state="disabled")

        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill="x", pady=5)
        ttk.Button(btn_frame, text="Close", command=win.destroy).pack(side="right")

    # Build
    def _start_build(self):
        threading.Thread(target=self._build_thread, daemon=True).start()

    def _build_thread(self):
        try:
            self.status.set("Building...")
            asm = Path(self.var_asm.get())
            if not asm.exists():
                self.status.set("Error: Source .asm not found.")
                return

            wd, base, com, dsk, obj, log = self._out_paths()
            logger = FileLogger(log)
            self.last_log_path = log
            logger.line(f"Project: {asm}")
            logger.line(f"Working folder: {wd}")
            logger.line(f"Derived base: {base}")
            wd.mkdir(parents=True, exist_ok=True)

            z80asm = self.var_z80asm.get().strip() or "z80asm.exe"
            appmake = self.var_appmake.get().strip() or "z88dk-appmake.exe"

            # Clean any prior .com variants in BOTH locations
            asm_dir = asm.parent
            _remove_com_variants(wd, base)
            if asm_dir != wd:
                _remove_com_variants(asm_dir, base)
            if obj.exists():
                try:
                    obj.unlink()
                except Exception:
                    pass
            if dsk.exists():
                try:
                    dsk.unlink()
                except Exception:
                    pass

            env = self._make_env_with_z88dk()

            # Assemble -> COM
            args = [z80asm, "-v", "-b", str(asm), f"-o{com.name}"]
            rc, output = logger.stream_proc(args, cwd=str(wd), env=env)
            if rc != 0:
                self.status.set("Build failed — see log.")
                logger.line(f"ERROR: assembler failed rc={rc}")
                msg = output or f"{z80asm} failed with exit code {rc}.\nLog: {log}"
                self.root.after(
                    0, self._show_error_window, "Assembly Error", msg
                )
                return

            # Normalise after assembler
            final_com = _normalise_to_single_uppercase_com(wd, asm_dir, base)
            if not final_com.exists():
                self.status.set("Error: COM was not created. See log.")
                logger.line("ERROR: COM not produced.")
                return

            # Remove object file if any
            if obj.exists():
                try:
                    obj.unlink()
                except Exception:
                    pass

            # Make DSK
            fmt = self.var_cpmdisk_fmt.get().strip() or DEFAULT_FMT
            args = [
                appmake,
                "+cpmdisk",
                "-f",
                fmt,
                "-b",
                final_com.name,
                "-o",
                dsk.name,
            ]
            rc, output = logger.stream_proc(args, cwd=str(wd), env=env)
            if rc != 0:
                self.status.set("Build failed — see log.")
                logger.line(f"ERROR: appmake failed rc={rc}")
                msg = output or f"{appmake} failed with exit code {rc}.\nLog: {log}"
                self.root.after(
                    0, self._show_error_window, "Disk Image Error", msg
                )
                return

            # Normalise again in case appmake recreated a lowercase copy
            final_com = _normalise_to_single_uppercase_com(wd, asm_dir, base)

            self.status.set(
                f"Build OK — COM: {final_com.name}  DSK: {dsk.name}"
            )
            logger.line("BUILD SUCCEEDED")
            logger.line(f"COM: {final_com}")
            logger.line(f"DSK: {dsk}")
            logger.line(f"Log saved to: {log}")
        except Exception as e:
            self.status.set(f"Build failed: {e}")
            if self.last_log_path:
                FileLogger(self.last_log_path).line(f"FATAL: {e}")
            self.root.after(
                0,
                self._show_error_window,
                "Build Error",
                f"Unexpected error:\n{type(e).__name__}: {e}",
            )

    # Clean
    def _clean_outputs(self):
        wd, base, com, dsk, obj, log = self._out_paths()
        asm = Path(self.var_asm.get())
        asm_dir = asm.parent if asm.exists() else wd
        removed = []
        candidates = [
            wd / f"{base}.COM",
            wd / f"{base}.com",
            asm_dir / f"{base}.COM",
            asm_dir / f"{base}.com",
            dsk,
            obj,
            log,
        ]
        for p in candidates:
            if p.exists():
                try:
                    p.unlink()
                    removed.append(p.name)
                except Exception:
                    pass
        self.status.set("Removed: " + (", ".join(removed) if removed else "nothing"))

    # Run
    def _start_run(self):
        threading.Thread(target=self._run_thread, daemon=True).start()

    def _run_thread(self):
        try:
            self.status.set("Launching MAME...")
            wd, base, com, dsk, obj, log = self._out_paths()
            logger = FileLogger(log)
            self.last_log_path = log

            if not dsk.exists():
                logger.line("No .dsk found, building first...")
                self._build_thread()
                if not dsk.exists():
                    self.status.set("Cannot run — .dsk not available.")
                    logger.line("ERROR: .dsk not available after build.")
                    return

            mame = self.var_mame.get().strip() or "mame.exe"
            dos80 = Path(self.var_dos80.get())
            if not dos80.exists():
                self.status.set("Error: System Disk not found.")
                logger.line("ERROR: System Disk .dsk missing.")
                self.root.after(
                    0,
                    self._show_error_window,
                    "MAME Error",
                    f"System disk not found:\n{dos80}",
                )
                return

            args = []
            if self.var_video_soft.get():
                args += ["-video", "soft"]
            args += ["-window" if self.var_windowed.get() else "-nowindow"]
            if self.var_ui_active.get():
                args += ["-ui_active"]
            if self.var_skip_intro.get():
                args += ["-skip_gameinfo"]
            res = (self.var_resolution.get() or "").strip()
            if res:
                args += ["-resolution", res]

            cmd = [
                mame,
                *args,
                "-rompath",
                self.var_rompath.get().strip(),
                "einstein",
                "-flop1",
                str(dos80),
                "-flop2",
                str(dsk),
            ]
            env = os.environ.copy()

            rc, output = logger.stream_proc(cmd, cwd=str(wd), env=env)
            if rc != 0:
                self.status.set("MAME failed — see log.")
                logger.line(f"ERROR: MAME failed rc={rc}")
                msg = output or f"MAME failed with exit code {rc}.\nLog: {log}"
                self.root.after(
                    0, self._show_error_window, "MAME Error", msg
                )
                return

            self.status.set("MAME finished. See log for details.")
            logger.line("MAME FINISHED")
        except Exception as e:
            self.status.set(f"MAME error: {e}")
            if self.last_log_path:
                FileLogger(self.last_log_path).line(f"FATAL: {e}")
            self.root.after(
                0,
                self._show_error_window,
                "MAME Error",
                f"Unexpected error:\n{type(e).__name__}: {e}",
            )


def main():
    if THEME:
        window = tb.Window(themename="cosmo")
        app = App(window)
        window.protocol("WM_DELETE_WINDOW", app.on_close)
        window.mainloop()
    else:
        root = tk.Tk()
        app = App(root)
        root.protocol("WM_DELETE_WINDOW", app.on_close)
        root.mainloop()


if __name__ == "__main__":
    main()
