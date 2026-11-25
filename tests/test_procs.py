import os
import subprocess
import sys
import time

import psutil
import pytest

from pr7sm import actions, procs

PARENT_OF_A_CHILD = ("import subprocess, sys, time\n"
                     "subprocess.Popen([sys.executable, '-c', 'import time\\nwhile True: time.sleep(0.2)'])\n"
                     "while True: time.sleep(0.2)")


def test_the_tree_puts_children_under_their_parents(spawn):
    p = spawn(PARENT_OF_A_CHILD)
    time.sleep(0.5)
    s = procs.Sampler().sample()
    me = s.procs[os.getpid()]
    assert p.pid in me.children                                           # our child under us
    child = s.procs[p.pid]
    grand = child.children[0]
    assert s.procs[grand].depth == child.depth + 1 == me.depth + 2
    order = s.order
    assert order.index(os.getpid()) < order.index(p.pid) < order.index(grand)     # parents before children
    assert set(order) == set(s.procs)


def test_a_reused_pid_is_not_the_parent():
    a = procs.Proc(10, 1, "old parent", started=200.0)
    b = procs.Proc(11, 10, "child", started=100.0)                         # started before its "parent": not its child
    c = procs.Proc(12, 99, "orphan", started=150.0)                        # its parent is gone
    d = procs.Proc(13, 10, "real child", started=300.0)
    ps = {x.pid: x for x in (a, b, c, d)}
    order = procs.tree(ps)
    assert a.children == [13] and b.depth == 0 and c.depth == 0 and d.depth == 1
    assert order == [11, 12, 10, 13]
    idle, system = procs.Proc(0, 0, "System Idle Process"), procs.Proc(4, 0, "System")
    lone = procs.Proc(20, 0, "parent 0", started=5.0)                     # parent 0 = none: never under Idle
    ps = {x.pid: x for x in (idle, system, lone)}
    procs.tree(ps)
    assert idle.children == [] and lone.depth == 0 and system.depth == 0


def test_cpu_comes_from_the_difference_between_samples(spawn):
    busy = spawn("while True: pass")
    idle = spawn()
    s = procs.Sampler()
    first = s.sample()
    assert first.procs[busy.pid].cpu is None                               # one sample can't tell
    time.sleep(1.0)
    snap = s.sample()
    one_core = 100 / (psutil.cpu_count() or 1)
    assert snap.procs[busy.pid].cpu > one_core * 0.5                       # spinning: about a whole core
    assert snap.procs[idle.pid].cpu < one_core * 0.2
    t = snap.totals
    assert 0 < t.cpu <= 100 and t.physical_total > 0 and t.commit_limit >= t.commit > 0 and t.processes > 3
    assert len(s.history["cpu"]) == 2 and len(s.proc_history[busy.pid]["cpu"]) == 2


def test_new_ending_suspended_and_own(spawn):
    s = procs.Sampler(highlight=0.8)
    s.sample()
    p = spawn()
    assert s.sample().procs[p.pid].kind == "new"
    time.sleep(1.0)
    snap = s.sample()
    assert snap.procs[p.pid].kind == "own" and snap.procs[os.getpid()].kind == "own"
    actions.suspend(p.pid)
    time.sleep(0.2)
    assert s.sample().procs[p.pid].kind == "suspended"
    actions.resume(p.pid)
    actions.kill(p.pid)
    p.wait(5)
    gone = s.sample().procs[p.pid]
    assert gone.kind == "ending" and gone.gone                              # red for a moment
    time.sleep(1.0)
    assert p.pid not in s.sample().procs                                   # then gone from the list


def test_kill_tree_ends_the_children_too(spawn):
    p = spawn(PARENT_OF_A_CHILD)
    time.sleep(0.5)
    kids = psutil.Process(p.pid).children(recursive=True)
    assert kids
    assert actions.kill_tree(p.pid) == 1 + len(kids)
    assert not psutil.pid_exists(p.pid) or psutil.Process(p.pid).status() == psutil.STATUS_ZOMBIE
    assert all(not psutil.pid_exists(k.pid) or psutil.Process(k.pid).status() == psutil.STATUS_ZOMBIE for k in kids)


def test_priority(spawn):
    p = spawn()
    actions.set_priority(p.pid, "Below normal")
    assert actions.priority(p.pid) == "Below normal"
    with pytest.raises(actions.Problem):
        actions.set_priority(999_999_999 if sys.platform != "win32" else 4_000_000, "Normal")


def test_dlls_handles_and_find(spawn, tmp_path):
    f = tmp_path / "pr7sm-held-open.txt"
    holder = spawn(f"f = open({str(f)!r}, 'w')\nimport time\nwhile True: time.sleep(0.2)")
    rows = actions.dlls(holder.pid)
    lib = "libc" if sys.platform != "win32" else "kernel32.dll"            # a library every Python process maps
    assert any(lib in r.name.casefold() for r in rows) and all(os.path.isabs(r.path) for r in rows)
    assert any(r.path == str(f) for r in actions.handles(holder.pid))
    hits = actions.find("pr7sm-held-open")
    assert [(h.pid, h.kind) for h in hits] == [(holder.pid, "File")]
    d = actions.details(holder.pid)
    assert d["ppid"] == os.getpid() and "pr7sm-held-open" in d["cmdline"] and d["threads"] >= 1


def test_acting_on_an_ended_process_says_so():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait(5)
    for fn in (actions.kill, actions.suspend, actions.dlls):
        with pytest.raises(actions.Problem, match="already ended"):
            fn(p.pid)


def test_sizes_like_process_explorer():
    assert procs.human(8 * 1024) == "8 K" and procs.human(412.7 * 1024 ** 2) == "412.7 MB"
    assert procs.human(4.02 * 1024 ** 3) == "4.02 GB" and procs.rate(38.2 * 1024 ** 2) == "38.2 MB/s"
