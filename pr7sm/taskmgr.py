"""Replace Task Manager (Process Explorer's Options > Replace Task Manager).

Windows' "debugger" redirect for taskmgr.exe (Image File Execution Options) makes anything that starts Task Manager
(Ctrl+Shift+Esc, the taskbar's menu, Ctrl+Alt+Del) start PR7-SM instead, as `PR7-SM.exe /taskmgr <its path>`. It's
machine-wide, so it needs administrator rights: PR7-SM re-runs itself elevated for it (one UAC prompt). Both registry
views are set (32-bit programs read the other one). Only PR7-SM's own value is ever removed (Process Explorer's, or
another tool's, is left alone). PR7-W's Notepad replacement works the same way."""

from __future__ import annotations

import os
import sys
from pathlib import Path

IFEO = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\taskmgr.exe"
FLAG = "/taskmgr"


def available() -> bool:
    return os.name == "nt"


def launcher() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable]
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")
    return [str(pyw if pyw.exists() else py), "-m", "pr7sm"]


def debugger_command() -> str:
    return " ".join(f'"{p}"' if (" " in p or p.lower().endswith(".exe")) else p for p in launcher()) + " " + FLAG


def _views():
    import winreg
    return (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY)


def current_debugger() -> str:
    """The taskmgr.exe redirect now set ('' if none)."""
    if not available():
        return ""
    import winreg
    for view in _views():
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, IFEO, 0, winreg.KEY_READ | view) as k:
                v, _ = winreg.QueryValueEx(k, "Debugger")
                if v:
                    return v
        except OSError:
            pass
    return ""


def is_ours(value: str) -> bool:
    v = value.lower()
    return FLAG in v and ("pr7-sm" in v or "-m pr7sm" in v)


def is_replaced() -> bool:
    return is_ours(current_debugger())


def replace() -> None:
    """Set the redirect (needs administrator rights; raises PermissionError otherwise)."""
    import winreg
    for view in _views():
        with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, IFEO, 0, winreg.KEY_SET_VALUE | view) as k:
            winreg.SetValueEx(k, "Debugger", 0, winreg.REG_SZ, debugger_command())


def restore() -> None:
    """Remove the redirect, if it's PR7-SM's (another program's is left alone)."""
    import winreg
    for view in _views():
        try:
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, IFEO, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE | view)
        except OSError:
            continue
        try:
            v, _ = winreg.QueryValueEx(k, "Debugger")
            if is_ours(v):
                winreg.DeleteValue(k, "Debugger")
        except OSError:
            pass
        finally:
            winreg.CloseKey(k)


def run_elevated(arg: str) -> int:
    """Run PR7-SM with `arg` as administrator and wait for it; -1 when the UAC prompt was declined."""
    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]
    parts = launcher()
    info = SHELLEXECUTEINFOW(cbSize=ctypes.sizeof(SHELLEXECUTEINFOW), fMask=0x00000040,      # NOCLOSEPROCESS
                             lpVerb="runas", lpFile=parts[0], lpParameters=" ".join(parts[1:] + [arg]), nShow=0)
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)) or not info.hProcess:
        return -1
    ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, 60_000)
    code = wintypes.DWORD()
    ctypes.windll.kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(info.hProcess)
    return code.value


def restart_as_admin() -> bool:
    """Process Explorer's File > Show Details for All Processes: start PR7-SM again elevated (this one then closes)."""
    import ctypes
    parts = launcher()
    r = ctypes.windll.shell32.ShellExecuteW(None, "runas", parts[0], " ".join(parts[1:]), None, 1)
    return r > 32


def run(action: str) -> int:
    """--replace-taskmgr / --restore-taskmgr (the elevated helper, and the uninstaller)."""
    if not available():
        print("Replacing Task Manager is for Windows.")
        return 1
    try:
        (replace if action == "--replace-taskmgr" else restore)()
        return 0
    except PermissionError:
        print(f"{action} needs administrator rights.")
        return 5
