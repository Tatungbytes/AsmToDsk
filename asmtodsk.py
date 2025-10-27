#!/usr/bin/env python3
# AsmToDsk.py
# Z80 .asm -> CP/M .COM -> Tatung Einstein .DSK, plus one-click Run in MAME.

APP_NAME = "AsmToDsk"
APP_VERSION = "2.0.1"
APP_TITLE = f"{APP_NAME} v{APP_VERSION}"

import os
import shutil
import subprocess
import threading
from pathlib import Path
import sys
import datetime
import tkinter as tk

# Require a GUI
if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
    print("No graphical display detected. Start a desktop session or use SSH with -X, then run: python3 asmtodsk.py")
    sys.exit(1)

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

HARDCODED = {
    "z80asm": "/home/tatungbytes/z88dk/bin/z80asm",
    "appmake": "/home/tatungbytes/z88dk/bin/z88dk-appmake",
    "workdir": "/home/tatungbytes/Desktop",
    "mame": "/usr/games/mame",
    "system_dsk": "/home/tatungbytes/Documents/Disk Images/DOS80.DSK",
    "rompath": "/home/tatungbytes/.mame/roms",
}

LOG_DIR = Path("/home/tatungbytes/Documents/Logs")

def ensure_runtime_dir_env(env: dict) -> dict:
    if "XDG_RUNTIME_DIR" not in env or not env["XDG_RUNTIME_DIR"]:
        cand = f"/run/user/{os.getuid()}"
        if os.path.isdir(cand):
            env["XDG_RUNTIME_DIR"] = cand
        else:
            tmp = f"/tmp/runtime-{os.environ.get('USER','user')}"
            os.makedirs(tmp, mode=0o700, exist_ok=True)
            env["XDG_RUNTIME_DIR"] = tmp
    return env

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
        proc = subprocess.Popen(args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:
            self._write(line)
        rc = proc.wait()
        if rc != 0:
            raise subprocess.CalledProcessError(rc, args)

def _remove_com_variants(folder: Path, base_stem: str):
    wanted_lower = f"{base_stem.lower()}.com"
    try:
        for p in folder.iterdir():
            if p.is_file() and p.name.lower() == wanted_lower:
                p.unlink()
    except FileNotFoundError:
        pass

def _normalise_to_single_uppercase_com(wd: Path, asm_dir: Path, base_stem: str) -> Path:
    wanted_lower = f"{base_stem.lower()}.com"
    candidates = []

    for folder in {wd, asm_dir}:
        if folder.exists():
            for p in folder.iterdir():
                if p.is_file() and p.name.lower() == wanted_lower:
                    candidates.append(p)

    desired = wd / f"{base_stem}.COM"
    keep = None
    if desired in candidates:
        keep = desired
    elif candidates:
        keep = max(candidates, key=lambda p: p.stat().st_mtime)

    if keep and keep != desired:
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

        self.var_z80asm = tk.StringVar(value=HARDCODED["z80asm"])
        self.var_appmake = tk.StringVar(value=HARDCODED["appmake"])
        self.var_asm = tk.StringVar()
        self.var_workdir = tk.StringVar(value=HARDCODED["workdir"])
        self.var_origin = tk.StringVar(value=DEFAULT_ORIGIN)
        self.var_cpmdisk_fmt = tk.StringVar(value=DEFAULT_FMT)
        self.var_mame = tk.StringVar(value=HARDCODED["mame"])
        self.var_dos80 = tk.StringVar(value=HARDCODED["system_dsk"])
        self.var_rompath = tk.StringVar(value=HARDCODED["rompath"])
        self.var_video_soft = tk.BooleanVar(value=True)
        self.var_windowed = tk.BooleanVar(value=True)
        self.var_ui_active = tk.BooleanVar(value=True)
        self.var_skip_intro = tk.BooleanVar(value=True)
        self.var_resolution = tk.StringVar(value=DEFAULT_RESOLUTION)
        self.var_boot_direct = tk.BooleanVar(value=False)

        self.base_upper = ""
        self.last_log_path = None
        self.var_asm.trace_add("write", self._on_asm_changed)

        self._build_ui()
        self._fit_to_content()

    def _on_asm_changed(self, *_):
        """Update status when selecting a new .asm file."""
        p = self.var_asm.get().strip()
        self.base_upper = Path(p).stem.upper() if p else ""
        if self.base_upper:
            self.status.set(f"Selected project: {self.base_upper}.ASM")

    def _build_ui(self):
        pad = 8
        default_font = tkfont.nametofont("TkDefaultFont")
        bold_font = default_font.copy()
        bold_font.configure(weight="bold")

        frm = ttk.Frame(self.root, padding=10)
        frm.pack(fill="both", expand=True)

        lf_proj = ttk.LabelFrame(frm, text="Project")
        lf_proj.pack(fill="x", pady=(0, pad))
        self._row(lf_proj, "Source .asm:", self.var_asm, browse=True,
                  filetypes=[("Assembly", "*.asm *.ASM"), ("All files", "*.*")],
                  label_font=bold_font)
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

        ttk.Checkbutton(lf_mame, text="Boot directly (no DOS80, add loader)", variable=self.var_boot_direct).pack(side="top", padx=6, pady=4)

        actions = ttk.Frame(frm)
        actions.pack(fill="x", pady=(0, pad))
        ttk.Button(actions, text="Build COM + DSK", command=self._start_build).pack(side="left")
        ttk.Button(actions, text="Run in MAME", command=self._start_run).pack(side="left", padx=10)

        self.status = tk.StringVar(value="Ready")
        ttk.Label(frm, textvariable=self.status, anchor="w").pack(fill="x")

    def _fit_to_content(self):
        self.root.update_idletasks()
        req_w, req_h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        scr_w, scr_h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        width = min(req_w, scr_w - 120)
        height = min(req_h, scr_h - 120)
        x, y = (scr_w - width) // 2, (scr_h - height) // 2
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _row(self, parent, label, var, browse=False, browse_dir=False, filetypes=None, label_font=None):
        row = ttk.Frame(parent)
        row.pack(fill="x", padx=6, pady=4)
        lbl = ttk.Label(row, text=label, width=18, anchor="e")
        if label_font:
            lbl.configure(font=label_font)
        lbl.pack(side="left")
        entry = ttk.Entry(row, textvariable=var)
        entry.pack(side="left", fill="x", expand=True, padx=6)
        if browse:
            ttk.Button(row, text="Browse", command=lambda: self._browse_file(var, filetypes)).pack(side="left")
        if browse_dir:
            ttk.Button(row, text="Choose", command=lambda: self._browse_dir(var)).pack(side="left")

    def _browse_file(self, var, filetypes=None):
        path = filedialog.askopenfilename(title="Choose file", filetypes=filetypes or [("All files", "*.*")])
        if path:
            var.set(path)

    def _browse_dir(self, var):
        d = filedialog.askdirectory(title="Choose folder")
        if d:
            var.set(d)

    def _out_paths(self):
        wd = Path(self.var_workdir.get())
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
            self.status.set("Buildingâ¦")
            asm = Path(self.var_asm.get())
            if not asm.exists():
                self.status.set("Error: Source .asm not found.")
                return
            wd, base, com, dsk, obj, log = self._out_paths()
            logger = FileLogger(log)
            logger.line(f"Building {asm}")
            wd.mkdir(parents=True, exist_ok=True)
            z80asm, appmake = self.var_z80asm.get(), self.var_appmake.get()
            _remove_com_variants(wd, base)

            # Assemble
            logger.stream_proc([z80asm, "-v", "-b", str(asm), f"-o{com.name}"], cwd=str(wd))
            final_com = _normalise_to_single_uppercase_com(wd, asm.parent, base)
            if not final_com.exists():
                self.status.set("Error: COM not produced.")
                return

            # Create DSK
            fmt = self.var_cpmdisk_fmt.get().strip() or DEFAULT_FMT
            logger.stream_proc([appmake, "+cpmdisk", "-f", fmt, "-b", final_com.name, "-o", dsk.name], cwd=str(wd))

            self.status.set(f"Build OK â {dsk.name}")
        except Exception as e:
            self.status.set(f"Build failed: {e}")

    def _start_run(self):
        threading.Thread(target=self._run_thread, daemon=True).start()

    def _run_thread(self):
        try:
            wd, base, com, dsk, obj, log = self._out_paths()
            if not dsk.exists():
                self.status.set("Error: .DSK missing. Build first.")
                return

            mame = self.var_mame.get().strip()
            args = ["-window" if self.var_windowed.get() else "-nowindow"]
            if self.var_video_soft.get(): args += ["-video", "soft"]
            if self.var_ui_active.get(): args += ["-ui_active"]
            if self.var_skip_intro.get(): args += ["-skip_gameinfo"]

            rompath = self.var_rompath.get().strip()
            env = ensure_runtime_dir_env(os.environ.copy())

            # Boot Direct Mode
            if self.var_boot_direct.get():
                self.status.set("Injecting bootloaderâ¦")
                with open(dsk, "r+b") as f:
                    f.seek(0)
                    boot = bytes([0x21,0x00,0x01,0x11,0x00,0x04,0xCD,0x20,0x00,0xED,0xB0,0xC3,0x00,0x01])
                    f.write(boot.ljust(512, b'\xE5'))
                cmd = [mame] + args + ["-rompath", rompath, "einstein", "-flop1", str(dsk)]
            else:
                dos80 = Path(self.var_dos80.get())
                cmd = [mame] + args + ["-rompath", rompath, "einstein", "-flop1", str(dos80), "-flop2", str(dsk)]

            subprocess.run(cmd, cwd=str(wd), env=env)
            self.status.set("MAME exited normally.")
        except Exception as e:
            self.status.set(f"Run failed: {e}")

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

