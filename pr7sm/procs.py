"""What runs, the way Process Explorer sees it: a snapshot of every process each refresh, through psutil. No Qt.

`Sampler.sample()` gives a `Snapshot`: every process (CPU from the difference since the last sample, private bytes,
working set, I/O), the tree (a process sits under its parent only if the parent started first: after a PID is reused,
the newer process isn't its parent), each row's colour kind (Process Explorer's: services, your own processes, new,
ending, suspended; new and ending last `highlight` seconds), and the totals for the graphs (CPU with kernel time,
commit charge, physical memory, disk I/O), with their history."""

from __future__ import annotations

import getpass
import os
import sys
import time
from collections import deque
from dataclasses import dataclass, field

import psutil

from . import winver

HISTORY = 300                      # samples kept for the graphs (5 minutes at one a second)
ATTRS = ["pid", "ppid", "name", "exe", "username", "create_time", "cpu_times", "memory_info", "status",
         "num_threads", "io_counters"]
KIND_ORDER = ("ending", "new", "suspended", "service", "own")


@dataclass
class Proc:
    pid: int
    ppid: int
    name: str
    exe: str = ""
    user: str = ""
    started: float = 0.0
    cpu: float | None = None        # percent of the whole machine since the last sample (None: the first sample)
    private: int = 0
    working: int = 0
    threads: int = 0
    status: str = ""
    io: float = 0.0                 # bytes a second read + written
    kind: str = ""
    description: str = ""
    company: str = ""
    version: str = ""
    depth: int = 0
    children: list[int] = field(default_factory=list)
    gone: bool = False


@dataclass
class Totals:
    cpu: float = 0.0
    kernel: float = 0.0
    commit: int = 0
    commit_limit: int = 0
    commit_peak: int = 0
    physical: int = 0
    physical_total: int = 0
    available: int = 0
    read: float = 0.0
    write: float = 0.0
    processes: int = 0
    cores: int = 1
    threads: int = 1
    ghz: float = 0.0


@dataclass
class Snapshot:
    procs: dict[int, Proc]
    order: list[int]                 # the tree, parents before children (each Proc has its depth)
    totals: Totals
    taken: float


def current_user() -> str:
    try:
        return getpass.getuser().casefold()
    except Exception:  # noqa: BLE001
        return ""


def same_user(owner: str, me: str) -> bool:
    """psutil names Windows users DOMAIN\\name; getpass gives the name alone."""
    return bool(owner) and owner.casefold().rsplit("\\", 1)[-1] == me


def service_pids() -> set[int]:
    """The processes Windows' service manager runs (Process Explorer's pink)."""
    if sys.platform != "win32":
        return set()
    out = set()
    try:
        for s in psutil.win_service_iter():
            try:
                pid = s.pid()
                if pid:
                    out.add(pid)
            except Exception:  # noqa: BLE001 - a service that went away meanwhile
                continue
    except Exception:  # noqa: BLE001
        pass
    return out


def commit_charge() -> tuple[int, int, int]:
    """(commit, limit, peak) in bytes: Windows' GetPerformanceInfo; elsewhere used + swap of total + swap."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class PERFORMANCE_INFORMATION(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("CommitTotal", ctypes.c_size_t), ("CommitLimit", ctypes.c_size_t),
                        ("CommitPeak", ctypes.c_size_t), ("PhysicalTotal", ctypes.c_size_t),
                        ("PhysicalAvailable", ctypes.c_size_t), ("SystemCache", ctypes.c_size_t),
                        ("KernelTotal", ctypes.c_size_t), ("KernelPaged", ctypes.c_size_t),
                        ("KernelNonpaged", ctypes.c_size_t), ("PageSize", ctypes.c_size_t),
                        ("HandleCount", wintypes.DWORD), ("ProcessCount", wintypes.DWORD),
                        ("ThreadCount", wintypes.DWORD)]
        pi = PERFORMANCE_INFORMATION()
        pi.cb = ctypes.sizeof(pi)
        if ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(pi), pi.cb):
            return pi.CommitTotal * pi.PageSize, pi.CommitLimit * pi.PageSize, pi.CommitPeak * pi.PageSize
    vm, sw = psutil.virtual_memory(), psutil.swap_memory()
    used = vm.total - vm.available + sw.used
    return used, vm.total + sw.total, used


class Sampler:
    def __init__(self, highlight: float = 2.0):
        self.highlight = highlight
        self.me = current_user()
        self.cpus = psutil.cpu_count() or 1
        self._prev: dict[int, tuple] = {}          # pid -> (create_time, cpu seconds, io bytes)
        self._first_seen: dict[int, float] = {}
        self._gone: dict[int, tuple[float, Proc]] = {}
        self._last = None
        self._sys_prev = None
        self._io_prev = None
        self._services: set[int] = set()
        self._services_at = 0.0
        self._peak = 0
        self.snapshot: Snapshot | None = None
        self.history = {k: deque(maxlen=HISTORY) for k in ("cpu", "kernel", "commit", "physical", "read", "write")}
        self.proc_history: dict[int, dict[str, deque]] = {}
        self.core_history: list[deque] = []
        psutil.cpu_percent(percpu=True)            # starts the per-core counters (the first answer is meaningless)

    # ---------------------------------------------------------------- one sample
    def sample(self, now: float | None = None) -> Snapshot:
        now = time.monotonic() if now is None else now
        wall = now - self._last if self._last is not None else None
        if time.time() - self._services_at > 10:          # the service list changes rarely and costs a little
            self._services = service_pids()
            self._services_at = time.time()
        procs: dict[int, Proc] = {}
        seen = set()
        for p in psutil.process_iter(ATTRS):
            info = p.info
            pid = info["pid"]
            seen.add(pid)
            ct = info.get("create_time") or 0.0
            times = info.get("cpu_times")
            cpu_s = (times.user + times.system) if times else 0.0
            io = info.get("io_counters")
            io_b = (io.read_bytes + io.write_bytes) if io else 0
            mem = info.get("memory_info")
            pr = Proc(pid, info.get("ppid") or 0, info.get("name") or "", info.get("exe") or "",
                      info.get("username") or "", ct, None,
                      getattr(mem, "private", None) or getattr(mem, "data", 0) if mem else 0,
                      mem.rss if mem else 0, info.get("num_threads") or 0, info.get("status") or "")
            prev = self._prev.get(pid)
            if prev is not None and prev[0] == ct and wall:
                pr.cpu = max(0.0, (cpu_s - prev[1]) / wall / self.cpus * 100)
                pr.io = max(0.0, (io_b - prev[2]) / wall)
            elif wall:
                pr.cpu = 0.0
            self._prev[pid] = (ct, cpu_s, io_b)
            if pid not in self._first_seen or self._first_seen[pid][0] != ct:
                self._first_seen[pid] = (ct, now if self._last is not None else -1e9)
            if pr.exe:
                d = winver.details(pr.exe)
                pr.description, pr.company, pr.version = d.get("description", ""), d.get("company", ""), \
                    d.get("version", "")
            pr.kind = self._kind(pr, now)
            procs[pid] = pr
            h = self.proc_history.setdefault(pid, {"cpu": deque(maxlen=HISTORY), "private": deque(maxlen=HISTORY),
                                                   "io": deque(maxlen=HISTORY)})
            h["cpu"].append(pr.cpu or 0.0)
            h["private"].append(pr.private)
            h["io"].append(pr.io)
        # ending: what was there last time and isn't now stays red for `highlight` seconds
        if self.snapshot is not None:
            for pid, old in self.snapshot.procs.items():
                if pid not in seen and not old.gone:
                    self._gone[pid] = (now, old)
        for pid, (when, old) in list(self._gone.items()):
            if now - when > self.highlight or pid in procs:
                del self._gone[pid]
                continue
            old.gone, old.kind, old.cpu = True, "ending", 0.0
            procs[pid] = old
        for pid in list(self._prev):
            if pid not in seen:
                del self._prev[pid]
                self.proc_history.pop(pid, None)
                self._first_seen.pop(pid, None)
        order = tree(procs)
        totals = self._totals(wall, len(seen))
        self._last = now
        self.snapshot = Snapshot(procs, order, totals, now)
        return self.snapshot

    def _kind(self, pr: Proc, now: float) -> str:
        first = self._first_seen.get(pr.pid, (0, -1e9))[1]
        if now - first <= self.highlight:
            return "new"
        if pr.status == psutil.STATUS_STOPPED:
            return "suspended"
        if pr.pid in self._services:
            return "service"
        if same_user(pr.user, self.me):
            return "own"
        return ""

    def _totals(self, wall, count) -> Totals:
        t = Totals(processes=count, cores=psutil.cpu_count(logical=False) or 1, threads=self.cpus)
        times = psutil.cpu_times()
        if self._sys_prev is not None:
            d = {f: getattr(times, f) - getattr(self._sys_prev, f) for f in times._fields}
            total = sum(d.values()) or 1.0
            idle = d.get("idle", 0.0) + d.get("iowait", 0.0)
            t.cpu = max(0.0, min(100.0, 100 * (total - idle) / total))
            t.kernel = max(0.0, min(t.cpu, 100 * (d.get("system", 0.0) + d.get("interrupt", 0.0)
                                                  + d.get("irq", 0.0) + d.get("softirq", 0.0)) / total))
        self._sys_prev = times
        vm = psutil.virtual_memory()
        t.physical_total, t.available = vm.total, vm.available
        t.physical = vm.total - vm.available
        t.commit, t.commit_limit, peak = commit_charge()
        self._peak = max(self._peak, peak, t.commit)
        t.commit_peak = self._peak
        try:
            io = psutil.disk_io_counters()
        except Exception:  # noqa: BLE001 - no disks visible (some containers)
            io = None
        if io is not None and self._io_prev is not None and wall:
            t.read = max(0.0, (io.read_bytes - self._io_prev.read_bytes) / wall)
            t.write = max(0.0, (io.write_bytes - self._io_prev.write_bytes) / wall)
        self._io_prev = io
        try:
            f = psutil.cpu_freq()
            t.ghz = (f.current or 0) / 1000 if f else 0.0
        except Exception:  # noqa: BLE001
            pass
        cores = psutil.cpu_percent(percpu=True)
        while len(self.core_history) < len(cores):
            self.core_history.append(deque(maxlen=HISTORY))
        for d, v in zip(self.core_history, cores):
            d.append(v)
        h = self.history
        h["cpu"].append(t.cpu)
        h["kernel"].append(t.kernel)
        h["commit"].append(100 * t.commit / t.commit_limit if t.commit_limit else 0.0)
        h["physical"].append(100 * t.physical / t.physical_total if t.physical_total else 0.0)
        h["read"].append(t.read)
        h["write"].append(t.write)
        return t


def tree(procs: dict[int, Proc]) -> list[int]:
    """Parents before children, each with its depth. A parent that started after its "child" (a reused PID) isn't
    its parent, and a process whose parent is gone is a top-level row (Process Explorer does both)."""
    for p in procs.values():
        p.children = []
    roots = []
    for p in sorted(procs.values(), key=lambda p: (p.started, p.pid)):
        parent = procs.get(p.ppid) if p.ppid else None      # parent 0 means none (Idle adopts nobody)
        if parent is not None and parent.pid != p.pid and parent.started <= p.started and p.pid not in (0, 4):
            parent.children.append(p.pid)
        else:
            roots.append(p.pid)
    order: list[int] = []
    stack = [(pid, 0) for pid in reversed(roots)]
    while stack:
        pid, depth = stack.pop()
        procs[pid].depth = depth
        order.append(pid)
        stack.extend((c, depth + 1) for c in reversed(procs[pid].children))
    return order


def human(n: float) -> str:
    """Process Explorer's sizes: K below a megabyte, then MB, GB."""
    if n < 1024 ** 2:
        return f"{n / 1024:,.0f} K"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:,.1f} MB"
    return f"{n / 1024 ** 3:,.2f} GB"


def rate(n: float) -> str:
    if n < 1024 ** 2:
        return f"{n / 1024:,.0f} KB/s"
    return f"{n / 1024 ** 2:,.1f} MB/s"


def is_admin() -> bool:
    if sys.platform == "win32":
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:  # noqa: BLE001
            return False
    return os.geteuid() == 0
