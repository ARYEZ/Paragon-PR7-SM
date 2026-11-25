"""What Process Explorer does to a process, and what it shows about one. No Qt.

kill / kill_tree (children first, so none are left behind under a new parent) / suspend / resume / set_priority;
dlls (the images mapped into it: DLLs and the .exe), handles (the files and connections it has open), find (a DLL or
handle by part of its name, across every process). Each says what went wrong as `Problem` (access denied: run as
administrator to act on other users' and system processes)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

import psutil

from . import winver

PRIORITIES = ["Realtime", "High", "Above normal", "Normal", "Below normal", "Idle"]


class Problem(Exception):
    pass


def _proc(pid: int) -> psutil.Process:
    try:
        return psutil.Process(pid)
    except psutil.NoSuchProcess:
        raise Problem("That process has already ended.") from None


def _do(fn, what: str):
    try:
        return fn()
    except psutil.NoSuchProcess:
        raise Problem("That process has already ended.") from None
    except psutil.AccessDenied:
        raise Problem(f"Windows didn't allow {what}: run PR7-SM as administrator for other users' and system "
                      "processes.") from None


def kill(pid: int, wait: float = 3.0):
    p = _proc(pid)
    _do(p.kill, "ending it")
    try:
        p.wait(wait)
    except psutil.TimeoutExpired:
        raise Problem("It didn't end in time.") from None
    except psutil.NoSuchProcess:
        pass


def kill_tree(pid: int, wait: float = 3.0) -> int:
    """The process and everything it started, the deepest first. Returns how many ended."""
    p = _proc(pid)
    family = _do(lambda: p.children(recursive=True), "listing what it started")
    victims = list(reversed(family)) + [p]
    for v in victims:
        try:
            v.kill()
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied:
            raise Problem(f"Windows didn't allow ending {v.name()} ({v.pid}): run PR7-SM as administrator.") from None
    gone, alive = psutil.wait_procs(victims, timeout=wait)
    if alive:
        raise Problem(f"{len(alive)} of them didn't end in time.")
    return len(gone)


def suspend(pid: int):
    _do(_proc(pid).suspend, "suspending it")


def resume(pid: int):
    _do(_proc(pid).resume, "resuming it")


def _priority_values():
    if sys.platform == "win32":
        return [psutil.REALTIME_PRIORITY_CLASS, psutil.HIGH_PRIORITY_CLASS, psutil.ABOVE_NORMAL_PRIORITY_CLASS,
                psutil.NORMAL_PRIORITY_CLASS, psutil.BELOW_NORMAL_PRIORITY_CLASS, psutil.IDLE_PRIORITY_CLASS]
    return [-20, -10, -5, 0, 10, 19]                   # nice values for the same six steps


def set_priority(pid: int, name: str):
    value = dict(zip(PRIORITIES, _priority_values()))[name]
    _do(lambda: _proc(pid).nice(value), "changing its priority")


def priority(pid: int) -> str:
    try:
        v = psutil.Process(pid).nice()
    except (psutil.Error, OSError):
        return ""
    values = _priority_values()
    if v in values:
        return PRIORITIES[values.index(v)]
    if sys.platform != "win32":                         # nice values between the six steps
        return PRIORITIES[min(range(6), key=lambda i: abs(values[i] - v))]
    return ""


@dataclass
class Row:
    name: str
    description: str
    company: str
    path: str
    kind: str = "DLL"


def dlls(pid: int) -> list[Row]:
    """The images mapped into the process (DLLs and its .exe; on Linux shared objects), with their file details."""
    maps = _do(lambda: _proc(pid).memory_maps(grouped=True), "reading its DLLs")
    seen, out = set(), []
    for m in maps:
        path = m.path
        low = path.casefold()
        if not path or path.startswith("[") or low in seen or not os.path.isabs(path):
            continue
        if not (low.endswith((".dll", ".exe", ".sys", ".drv", ".ocx", ".cpl")) or ".so" in os.path.basename(low)):
            continue
        seen.add(low)
        d = winver.details(path)
        out.append(Row(os.path.basename(path), d.get("description", ""), d.get("company", ""), path))
    return sorted(out, key=lambda r: r.name.casefold())


def handles(pid: int) -> list[Row]:
    """Its open files and network connections (the handles worth seeing; Process Explorer shows these first)."""
    p = _proc(pid)
    out = [Row(os.path.basename(f.path), "", "", f.path, "File")
           for f in _do(p.open_files, "reading its handles")]
    try:
        conns = p.net_connections(kind="inet")
    except (psutil.AccessDenied, AttributeError):
        conns = []
    except psutil.NoSuchProcess:
        raise Problem("That process has already ended.") from None
    for c in conns:
        local = f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else ""
        remote = f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else ""
        proto = "TCP" if c.type == 1 else "UDP"
        out.append(Row(f"{proto} {local}" + (f" -> {remote}" if remote else ""), c.status or "", "", "", proto))
    return out


@dataclass
class Found:
    pid: int
    process: str
    kind: str
    path: str


def find(text: str, cancelled=lambda: False) -> list[Found]:
    """Process Explorer's Find Handle or DLL: every process with a DLL or open file whose path holds `text`."""
    t = text.casefold().strip()
    out: list[Found] = []
    if not t:
        return out
    for p in psutil.process_iter(["pid", "name"]):
        if cancelled():
            break
        try:
            for m in p.memory_maps(grouped=True):
                if t in m.path.casefold() and os.path.isabs(m.path):
                    out.append(Found(p.info["pid"], p.info["name"], "DLL", m.path))
            for f in p.open_files():
                if t in f.path.casefold():
                    out.append(Found(p.info["pid"], p.info["name"], "File", f.path))
        except (psutil.Error, OSError):
            continue
    return out


def details(pid: int) -> dict:
    """The Image tab: path, command line, folder, parent, user, start time, threads, DLL and handle counts."""
    p = _proc(pid)
    out = {"pid": pid}

    def get(key, fn):
        try:
            out[key] = fn()
        except (psutil.Error, OSError):
            out[key] = None
    get("name", p.name)
    get("exe", p.exe)
    get("cmdline", lambda: " ".join(f'"{a}"' if " " in a else a for a in p.cmdline()))
    get("cwd", p.cwd)
    get("user", p.username)
    get("started", p.create_time)
    get("ppid", p.ppid)
    get("parent", lambda: p.parent().name() if p.parent() else None)
    get("threads", p.num_threads)
    get("handles", lambda: p.num_handles() if hasattr(p, "num_handles") else p.num_fds())
    get("priority", lambda: priority(pid))
    get("environ", p.environ)
    get("thread_list", lambda: [(t.id, t.user_time, t.system_time) for t in p.threads()])
    try:
        out["connections"] = handles(pid)
    except Problem:
        out["connections"] = []
    d = winver.details(out.get("exe") or "")
    out.update({k: d.get(k, "") for k in ("description", "company", "version", "product")})
    return out
