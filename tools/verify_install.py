"""Check a real install of PR7-SM-Setup.exe (CI, Windows): verify_install.py installed|uninstalled

`installed`: the files, the Start menu entry, the uninstall entry, and the installed exe's --selftest (the real
system sampled, a process found under its parent, suspended, resumed and ended, file details read). `uninstalled`:
all of it gone, and Task Manager not redirected."""
import json
import os
import subprocess
import sys
import tempfile
import time
import winreg
from pathlib import Path

HKCU, HKLM = winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE
APP = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "PR7-SM"
SHORTCUT = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Paragon PR7-SM.lnk"
UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{DA18598E-10B7-4EA2-B221-71F0CFC56AA8}_is1"
IFEO = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\taskmgr.exe"


def value(root, path, name=""):
    try:
        with winreg.OpenKey(root, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def check(ok, what, p):
    print(("ok    " if ok else "FAIL  ") + what)
    if not ok:
        p.append(what)


def installed():
    p = []
    exe = APP / "PR7-SM.exe"
    for f in (exe, APP / "unins000.exe", APP / "_internal" / "pr7sm" / "fonts" / "Inter-Regular.ttf"):
        check(f.is_file(), f"file {f}", p)
    check(SHORTCUT.is_file(), "Start menu shortcut", p)
    check(value(HKCU, UNINSTALL, "DisplayName") == "Paragon PR7-SM", "Installed apps entry", p)
    check(not value(HKLM, IFEO, "Debugger"), "Task Manager not replaced (the task is unticked)", p)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "out.json"
        try:
            subprocess.run([str(exe), "--selftest", str(out)], timeout=180, check=False)
        except subprocess.TimeoutExpired:
            pass
        got = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
        check(got.get("processes", 0) > 20 and got.get("system_seen") is True and got.get("physical_total", 0) > 0
              and got.get("fonts") is True, f"the installed exe samples the system ({got})", p)
        check(got.get("found_child") is True and got.get("child_under_me") is True, "a new process sits under its parent", p)
        check(got.get("suspended") is True and got.get("resumed") is True and got.get("killed") is True,
              "it suspends, resumes and ends a process", p)
        check(got.get("dlls", 0) > 3 and got.get("described", 0) > 3, "DLLs and file details are read", p)
    return p


def uninstalled():
    deadline = time.time() + 60
    while True:
        p = []
        check(not (APP / "PR7-SM.exe").exists(), "program files removed", p)
        check(not SHORTCUT.exists(), "Start menu shortcut removed", p)
        check(value(HKCU, UNINSTALL, "DisplayName") is None, "Installed apps entry removed", p)
        check(not value(HKLM, IFEO, "Debugger"), "Task Manager not redirected", p)
        if not p or time.time() > deadline:
            return p
        print("... waiting for the uninstaller to finish")
        time.sleep(3)


if __name__ == "__main__":
    problems = {"installed": installed, "uninstalled": uninstalled}[sys.argv[1]]()
    print("\nALL OK" if not problems else f"\n{len(problems)} problem(s)")
    sys.exit(1 if problems else 0)
