"""Screenshots of the real PR7-SM window on a made-up Windows machine (a stand-in sampler: every process and number is
invented; the window code is the real one): QT_SCALE_FACTOR=2 python tools/screenshots.py OUT_DIR"""
import math
import os
import random
import sys
import tempfile
from collections import deque
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PR7SM_DATA"] = tempfile.mkdtemp()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tempfile.mkdtemp())

from pr7sm import actions, main_window, procs, theme  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots")
out.mkdir(parents=True, exist_ok=True)
app = QApplication([])
theme.load_fonts()
MB = 1024 ** 2

# (depth, name, cpu, private MB, working MB, pid, description, company, kind)
PROCS = [
    (0, "System Idle Process", 87.6, 0, 0.008, 0, "", "", ""),
    (0, "System", 0.4, 0.2, 4.1, 4, "", "", ""),
    (1, "Registry", "", 9.8, 61.4, 140, "", "", ""),
    (1, "smss.exe", "", 1.1, 1.3, 512, "Windows Session Manager", "Microsoft Corporation", ""),
    (1, "Memory Compression", "", 2.0, 412.7, 3104, "", "", ""),
    (0, "csrss.exe", 0.1, 2.6, 6.2, 760, "Client Server Runtime Process", "Microsoft Corporation", ""),
    (0, "wininit.exe", "", 1.6, 7.4, 852, "Windows Start-Up Application", "Microsoft Corporation", ""),
    (1, "services.exe", 0.2, 6.3, 11.9, 984, "Services and Controller app", "Microsoft Corporation", ""),
    (2, "svchost.exe", 0.1, 12.4, 31.0, 1128, "Host Process for Windows Services", "Microsoft Corporation", "service"),
    (2, "svchost.exe", "", 8.9, 22.6, 1196, "Host Process for Windows Services", "Microsoft Corporation", "service"),
    (2, "MsMpEng.exe", 1.2, 284.1, 231.5, 3880, "Antimalware Service Executable", "Microsoft Corporation", "service"),
    (2, "PR7-IS.exe", 0.1, 162.3, 188.0, 4412, "Paragon PR7-IS file search", "Paragon", "service"),
    (2, "spoolsv.exe", "", 5.7, 14.2, 2620, "Spooler SubSystem App", "Microsoft Corporation", "service"),
    (1, "lsass.exe", 0.1, 9.1, 24.3, 1004, "Local Security Authority Process", "Microsoft Corporation", ""),
    (0, "explorer.exe", 1.9, 96.4, 211.8, 6216, "Windows Explorer", "Microsoft Corporation", "own"),
    (1, "Resolve.exe", 6.4, 4120.0, 3388.2, 9032, "DaVinci Resolve", "Blackmagic Design", "own"),
    (1, "PR7-SM.exe", 0.6, 88.2, 121.7, 11240, "Paragon PR7-SM system monitor", "Paragon", "own"),
    (1, "PR7-M.exe", 0.9, 142.6, 176.3, 10388, "Paragon PR7-M media player", "Paragon", "own"),
    (1, "PR7-PM.exe", "", 61.0, 92.4, 8776, "Paragon PR7-PM password manager", "Paragon", "own"),
    (1, "PR7-CB.exe", "", 44.1, 70.9, 7004, "Paragon PR7-CB clipboard history", "Paragon", "own"),
    (1, "obs64.exe", 2.3, 512.8, 448.0, 12112, "OBS Studio", "OBS Project", "new"),
    (1, "ffmpeg.exe", "", 31.0, 40.2, 12544, "FFmpeg", "", "ending"),
    (1, "Notepad.exe", "", 18.2, 41.7, 9920, "Notepad", "Microsoft Corporation", "suspended"),
]
DLLS = [
    ("avcodec-61.dll", "FFmpeg codec library", "FFmpeg Project", r"C:\Program Files\Blackmagic Design\DaVinci Resolve"),
    ("cudart64_12.dll", "CUDA Runtime", "NVIDIA Corporation", r"C:\Program Files\Blackmagic Design\DaVinci Resolve"),
    ("d3d11.dll", "Direct3D 11 Runtime", "Microsoft Corporation", r"C:\Windows\System32"),
    ("Fusion.dll", "Fusion", "Blackmagic Design", r"C:\Program Files\Blackmagic Design\DaVinci Resolve"),
    ("kernel32.dll", "Windows NT BASE API Client DLL", "Microsoft Corporation", r"C:\Windows\System32"),
    ("ntdll.dll", "NT Layer DLL", "Microsoft Corporation", r"C:\Windows\System32"),
    ("Qt6Core.dll", "C++ Application Development Framework", "The Qt Company Ltd.",
     r"C:\Program Files\Blackmagic Design\DaVinci Resolve"),
]


def series(n, base, wobble, seed):
    r = random.Random(seed)
    v, out_ = base, []
    for i in range(n):
        v = max(4, min(94, v + r.uniform(-wobble, wobble) + 3 * math.sin(i / 7)))
        out_.append(v)
    return out_


class StandIn(procs.Sampler):
    """The made-up machine: the same snapshot each time, with five minutes of history behind it."""

    def sample(self, now=None):
        ps, stack = {}, []
        for n, (depth, name, cpu, priv, ws, pid, desc, comp, kind) in enumerate(PROCS):
            p = procs.Proc(pid, 0, name, f"C:\\Windows\\System32\\{name}" if name.endswith(".exe") else "",
                           "STUDIO\\me" if kind == "own" else "SYSTEM", float(n), cpu if cpu != "" else 0.0,
                           int(priv * MB), int(ws * MB), 8, "running", 0.0, kind, desc, comp)
            stack = stack[:depth]
            p.ppid = stack[-1] if stack else 0
            stack.append(pid)
            ps[pid] = p
        order = procs.tree(ps)
        t = procs.Totals(cpu=12.4, kernel=4.1, commit=int(9.21 * 1024 * MB), commit_limit=int(31.8 * 1024 * MB),
                         commit_peak=int(12.6 * 1024 * MB), physical=int(15.0 * 1024 * MB),
                         physical_total=int(31.9 * 1024 * MB), available=int(16.9 * 1024 * MB), read=31.4 * MB,
                         write=6.8 * MB, processes=214, cores=16, threads=32, ghz=4.2)
        h = self.history
        for k, (b, w, seed, scale) in {"cpu": (14, 6, 1, 1), "kernel": (5, 3, 2, 1), "commit": (29, .6, 3, 1),
                                       "physical": (47, .5, 4, 1), "read": (25, 14, 5, MB), "write": (9, 6, 6, MB)}.items():
            h[k] = deque((v * scale for v in series(300, b, w, seed)), maxlen=300)
        self.core_history = [deque(series(300, 12, 9, 10 + i), maxlen=300) for i in range(16)]
        self.proc_history = {9032: {"cpu": deque(series(300, 8, 5, 21)), "private": deque(
            (v * 60 * MB for v in series(300, 66, 1.5, 22))), "io": deque((v * MB for v in series(300, 20, 12, 23)))}}
        self.snapshot = procs.Snapshot(ps, order, t, 0.0)
        return self.snapshot


actions.dlls = lambda pid: [actions.Row(n, d, c, p + "\\" + n) for n, d, c, p in DLLS]
actions.details = lambda pid: {
    "pid": pid, "name": "Resolve.exe", "exe": r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe",
    "cmdline": r'"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe" "D:\Projects\Elseworld\Elseworld edit.drp"',
    "cwd": "D:\\Projects\\Elseworld\\", "user": "STUDIO\\me", "started": __import__("time").time() - 9660,
    "ppid": 6216, "parent": "explorer.exe", "threads": 96, "handles": 2184, "priority": "Normal", "environ": {},
    "thread_list": [], "connections": [], "description": "DaVinci Resolve", "company": "Blackmagic Design",
    "version": "20.1.0.0045", "product": "DaVinci Resolve"}
w = main_window.MainWindow(StandIn())
w.timer.stop()
w.sync = True
w.answers.update({"say": lambda k, t: None, "menu": lambda *a: None})
w.resize(1280, 960)
w.show()
w.refresh()
w.select(9032)
w.load_pane()
w.view.scrollToTop()
app.processEvents()


def shot(widget, name):
    app.processEvents()
    widget.grab().save(str(out / name))
    print(out / name)


shot(w, "processes.png")
w.answers["properties"] = lambda d: None
d = w.properties()
d.resize(760, 600)
d.show()
shot(d, "properties.png")
d.close()
theme.set_finish("aurora")
app.setPalette(theme.palette())
w.answers["system"] = lambda d: None
s = w.system_info()
s.setStyleSheet(main_window.stylesheet())
s.show()
shot(s, "system_aurora.png")
s.close()
theme.set_finish("obsidian")
w.close()
