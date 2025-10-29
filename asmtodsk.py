#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AsmToDsk – v2.3 (Cross-Platform Edition)
────────────────────────────────────────────
Z80 .ASM → CP/M .COM → Tatung Einstein .DSK
Works on Windows, Linux, and macOS (Tkinter GUI)
────────────────────────────────────────────
"""

import os
import sys
import platform
import shutil
import subprocess
import threading
import datetime
from pathlib import Path
from shutil import which
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, font as tkfont

# Optional theming (ttkbootstrap if installed)
try:
    import ttkbootstrap as tb
    from ttkbootstrap.constants import *
    THEME = True
except Exception:
    THEME = False


APP_NAME = "AsmToDsk"
APP_VERSION = "2.3"
APP_TITLE = f"{APP_NAME} v{APP_VERSION}"

# ─────────────────────────────────────────────
# Environment setup and helpers
# ─────────────────────────────────────────────

HOME = Path.home()
DESKTOP = HOME / "Desktop"
DOCS = HOME / "Documents"
Z88DK_HOME = HOME / "z88dk"  # Windows default location for z88dk

def normalize_path(p: str) -> str:
    """Ensure any path uses correct OS separators and resolves properly."""
    return str(Path(p).expanduser().resolve())

def find_tool(name: str, default_win: Path, default_linux: str) -> str:
    """Find a tool in PATH or fallback to a platform default."""
    path = which(name)
    if path:
        return path
    return str(default_win) if os.name == "nt" else default_linux

HARDCODED = {
    "z80asm": find_tool("z80asm", Z88DK_HOME / "bin/z80asm.exe", "/usr/bin/z80asm"),
    "appmake": find_tool("z88dk-appmake", Z88DK_HOME / "bin/z88dk-appmake.exe", "/usr/bin/z88dk-appmake"),
    "workdir": str(DESKTOP),
    "mame": find_tool("mame", Path("C:/Program Files/MAME/mame.exe"), "/usr/games/mame"),
    "system_dsk": str(DOCS / "Disk Images/DOS80.DSK"),
    "rompath": str(HOME / ("MAME/roms" if os.name == "nt" else ".mame/roms")),
}

LOG_DIR = DOCS / "Logs"

# ─────────────────────────────────────────────
# Display check (Linux only)
# ─────────────────────────────────────────────
if platform.system() not in ("Windows", "Darwin"):
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        print("No graphical display detected. Start a desktop session or use SSH with -X.")
        sys.exit(1)

# ─────────────────────────────────────────────
# File logger utility
# ─────────────────────────────────────────────

class FileLogger:
    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._write(f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {APP_TITLE}\n")

    def _write(self, text: str):
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(text)

    def line(self, text: str):
        self._write(text if text.endswith("\n") else text + "\n")

    def cmd(self, args):
        self.line(f"$ {' '.join(args)}")

    def stream_proc(self, args, cwd=None, env=None):
        self.cmd(args)
        proc = subprocess.Popen(args, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:
            self._write(line)
        rc = proc.wait()
        if rc != 0:
            raise subprocess.CalledProcessError(rc, args)

def ensure_runtime_dir_env(env: dict) -> dict:
    """Ensure XDG_RUNTIME_DIR exists (only relevant for Linux)."""
    if platform.system() == "Linux":
        if "XDG_RUNTIME_DIR" not in env or not env["XDG_RUNTIME_DIR"]:
            cand = f"/run/user/{os.getuid()}"
            if os.path.isdir(cand):
                env["XDG_RUNTIME_DIR"] = cand
            else:
                tmp = f"/tmp/runtime-{os.environ.get('USER', 'user')}"
                os.makedirs(tmp, mode=0o700, exist_ok=True)
                env["XDG_RUNTIME_DIR"] = tmp
    return env

# ─────────────────────────────────────────────
# Helpers for COM + DSK files
# ─────────────────────────────────────────────

def _remove_com_variants(folder: Path, base_stem: str):
    wanted_lower = f"{base_stem.lower()}.com"
    for p in folder.glob("*"):
        if p.is_file() and p.name.lower() == wanted_lower:
            p.unlink(missing_ok=True)

def _normalise_to_single_uppercase_com(wd: Path, asm_dir: Path, base_stem: str) -> Path:
    wanted_lower = f"{base_stem.lower()}.com"
    candidates = []
    for folder in {wd, asm_dir}:
        if folder.exists():
            for p in folder.iterdir():
                if p.is_file() and p.name.lower() == wanted_lower:
                    candidates.append(p)
    desired = wd / f"{base_stem}.COM"
    keep = desired if desired in candidates else (max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None)
    if keep and keep != desired:
        shutil.move(str(keep), str(desired))
    for p in candidates:
        if p.exists() and p != desired:
            p.unlink(missing_ok=True)
    return desired

# ─────────────────────────────────────────────
# Main GUI App
# ─────────────────────────────────────────────

class App:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.resizable(True, True)

        self.var_z80asm = tk.StringVar(value=HARDCODED["z80asm"])
        self.var_appmake = tk.StringVar(value=HARDCODED["appmake"])
        self.var_asm = tk.StringVar()
        self.var_workdir = tk.StringVar(value=HARDCODED["workdir"])
        self.var_origin = tk.StringVar(value="256")
        self.var_cpmdisk_fmt = tk.StringVar(value="einstein")
        self.var_mame = tk.StringVar(value=HARDCODED["mame"])
        self.var_dos80 = tk.StringVar(value=HARDCODED["system_dsk"])
        self.var_rompath = tk.StringVar(value=HARDCODED["rompath"])

        self.base_upper = ""
        self.status = tk.StringVar(value="Ready")

        self.var_asm.trace_add("write", self._on_asm_changed)

        self._build_ui()
        self._fit_to_content()

    # ─────────────── UI setup ───────────────

    def _on_asm_changed(self, *_):
        p = self.var_asm.get().strip()
        self.base_upper = Path(p).stem.upper() if p else ""
        if self.base_upper:
            self.status.set(f"Selected project: {self.base_upper}.ASM")

    def _build_ui(self):
        pad = 8
        frm = ttk.Frame(self.root, padding=10)
        frm.pack(fill="both", expand=True)

        lf_proj = ttk.LabelFrame(frm, text="Project")
        lf_proj.pack(fill="x", pady=(0, pad))
        self._row(lf_proj, "Source .asm:", self.var_asm, browse=True,
                  filetypes=[("Assembly", "*.asm *.ASM"), ("All files", "*.*")])
        self._row(lf_proj, "Working folder:", self.var_workdir, browse_dir=True)

        lf_tools = ttk.LabelFrame(frm, text="Tools")
        lf_tools.pack(fill="x", pady=(0, pad))
        self._row(lf_tools, "z80asm:", self.var_z80asm, browse=True)
        self._row(lf_tools, "z88dk-appmake:", self.var_appmake, browse=True)

        lf_opts = ttk.LabelFrame(frm, text="Build Options")
        lf_opts.pack(fill="x", pady=(0, pad))
        self._row(lf_opts, "Origin (info):", self.var_origin)
        self._row(lf_opts, "CP/M Disk Format:", self.var_cpmdisk_fmt)

        lf_mame = ttk.LabelFrame(frm, text="Run in MAME")
        lf_mame.pack(fill="x", pady=(0, pad))
        self._row(lf_mame, "mame:", self.var_mame, browse=True)
        self._row(lf_mame, "System Disk:", self.var_dos80, browse=True)
        self._row(lf_mame, "ROM path:", self.var_rompath, browse_dir=True)

        actions = ttk.Frame(frm)
        actions.pack(fill="x", pady=(0, pad))
        ttk.Button(actions, text="Build COM + DSK", command=self._start_build).pack(side="left")
        ttk.Button(actions, text="Run in MAME", command=self._start_run).pack(side="left", padx=10)

        ttk.Label(frm, textvariable=self.status, anchor="w").pack(fill="x")

    def _fit_to_content(self):
        self.root.update_idletasks()
        w, h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{min(w, sw - 120)}x{min(h, sh - 120)}+{(sw - w)//2}+{(sh - h)//2}")

    def _row(self, parent, label, var, browse=False, browse_dir=False, filetypes=None):
        row = ttk.Frame(parent)
        row.pack(fill="x", padx=6, pady=4)
        ttk.Label(row, text=label, width=18, anchor="e").pack(side="left")
        ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True, padx=6)
        if browse:
            ttk.Button(row, text="Browse", command=lambda: self._browse_file(var, filetypes)).pack(side="left")
        if browse_dir:
            ttk.Button(row, text="Choose", command=lambda: self._browse_dir(var)).pack(side="left")

    def _browse_file(self, var, filetypes=None):
        p = filedialog.askopenfilename(title="Choose file", filetypes=filetypes or [("All files", "*.*")])
        if p:
            var.set(normalize_path(p))

    def _browse_dir(self, var):
        d = filedialog.askdirectory(title="Choose folder")
        if d:
            var.set(normalize_path(d))

    # ─────────────── Build Process ───────────────

    def _out_paths(self):
        wd = Path(normalize_path(self.var_workdir.get()))
        base = self.base_upper or Path(self.var_asm.get()).stem.upper()
        com = wd / f"{base}.COM"
        dsk = wd / f"{base}.DSK"
        obj = wd / f"{base}.o"
        log = LOG_DIR / f"{base}_build.log"
        return wd, base, com, dsk, obj, log

    def _start_build(self):
        threading.Thread(target=self._build_thread, daemon=True).start()

    def _build_thread(self):
        try:
            self.status.set("Building…")
            asm = Path(normalize_path(self.var_asm.get()))
            if not asm.exists():
                self.status.set("Error: Source .asm not found.")
                return
            wd, base, com, dsk, obj, log = self._out_paths()
            wd.mkdir(parents=True, exist_ok=True)
            logger = FileLogger(log)
            logger.line(f"Building {asm}")
            _remove_com_variants(wd, base)

            z80asm = normalize_path(self.var_z80asm.get())
            appmake = normalize_path(self.var_appmake.get())

            logger.stream_proc([z80asm, "-v", "-b", str(asm), f"-o{com.name}"], cwd=str(wd))
            final_com = _normalise_to_single_uppercase_com(wd, asm.parent, base)
            if not final_com.exists():
                self.status.set("Error: COM not produced.")
                return

            fmt = self.var_cpmdisk_fmt.get().strip() or "einstein"
            logger.stream_proc([appmake, "+cpmdisk", "-f", fmt, "-b", final_com.name, "-o", dsk.name], cwd=str(wd))
            self.status.set(f"Build OK — {dsk.name}")
        except Exception as e:
            self.status.set(f"Build failed: {e}")

    # ─────────────── Run in MAME ───────────────

    def _start_run(self):
        threading.Thread(target=self._run_thread, daemon=True).start()

    def _run_thread(self):
        try:
            wd, base, com, dsk, obj, log = self._out_paths()
            if not dsk.exists():
                self.status.set("Error: .DSK missing. Build first.")
                return

            mame = Path(normalize_path(self.var_mame.get()))
            rompath = Path(normalize_path(self.var_rompath.get()))
            dos80 = Path(normalize_path(self.var_dos80.get()))
            env = ensure_runtime_dir_env(os.environ.copy())

            args = ["-window", "-ui_active", "-skip_gameinfo"]
            cmd = [str(mame), "-rompath", str(rompath), "einstein",
                   "-flop1", str(dos80), "-flop2", str(dsk)] + args

            subprocess.run(cmd, cwd=str(wd), env=env)
            self.status.set("MAME exited normally.")
        except Exception as e:
            self.status.set(f"Run failed: {e}")

# ─────────────────────────────────────────────
# Main Entry
# ─────────────────────────────────────────────

def main():
    if THEME:
        app = tb.Window(themename="cosmo")
        App(app)
        app.mainloop()
    else:
        root = tk.Tk()
        App(root)
        root.mainloop()

if __name__ == "__main__":
    main()
