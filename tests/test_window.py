import os
import time

import psutil
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from conftest import SLEEPER

PARENT_OF_A_CHILD = ("import subprocess, sys, time\n"
                     "subprocess.Popen([sys.executable, '-c', 'import time\\nwhile True: time.sleep(0.2)'])\n"
                     "while True: time.sleep(0.2)")


def shown(w):
    return [w.model.proc(r).pid for r in range(w.model.rowCount())]


def test_the_tree_shows_real_processes_under_their_parents(window, spawn):
    w = window
    p = spawn(PARENT_OF_A_CHILD)
    time.sleep(0.4)
    w.refresh(); w.refresh()
    rows = shown(w)
    assert os.getpid() in rows and p.pid in rows
    me, child = w.model.proc(rows.index(os.getpid())), w.model.proc(rows.index(p.pid))
    assert rows.index(os.getpid()) < rows.index(p.pid) and child.depth == me.depth + 1
    assert w.model.data(w.model.index(rows.index(p.pid), 4)) == str(p.pid)
    assert w.model.data(w.model.index(rows.index(p.pid), 0), Qt.ItemDataRole.UserRole + 1) is not None   # tinted (own)
    w.select(p.pid)
    w.set_collapsed(p.pid, True)
    assert len(shown(w)) == len(rows) - 1 and w.current_pid() == p.pid       # its child folded away
    w.set_collapsed(p.pid, False)
    assert len(shown(w)) == len(rows)


def test_sorting_flattens_and_the_third_click_brings_the_tree_back(window, spawn):
    w = window
    spawn("while True: pass")
    w.refresh(); time.sleep(0.6); w.refresh()
    w.sort_by(1)                                                           # CPU: the busiest first
    cpus = [w.model.proc(r).cpu or 0 for r in range(w.model.rowCount())]
    assert cpus == sorted(cpus, reverse=True) and w.model.data(w.model.index(0, 0), Qt.ItemDataRole.UserRole + 2) == 0
    assert "▼" in w.model.headerData(1, Qt.Orientation.Horizontal)
    w.sort_by(1)
    assert w.model.sort == (1, False)
    w.sort_by(1)
    assert w.model.sort is None and shown(w) == [pid for pid in w.sampler.snapshot.order]


def test_filter_and_a_refresh_that_keeps_the_selection(window, spawn):
    w = window
    p = spawn()
    w.refresh()
    w.select(p.pid)
    bar_before = w.view.verticalScrollBar().value()
    w.refresh()
    assert w.current_pid() == p.pid and w.view.verticalScrollBar().value() == bar_before
    QTest.keyClicks(w.filter, str(p.pid))
    assert shown(w) == [p.pid]
    w.filter.clear()
    assert len(shown(w)) > 3


def test_kill_and_kill_tree_from_the_keys(window, spawn):
    w = window
    asked = []
    w.answers["confirm"] = lambda text: asked.append(text) or True
    lone = spawn()
    family = spawn(PARENT_OF_A_CHILD)
    time.sleep(0.4)
    w.refresh()
    w.select(lone.pid)
    w.view.setFocus()
    QTest.keyClick(w.view, Qt.Key.Key_Delete)
    lone.wait(5)
    assert lone.returncode is not None and asked and "End python" in asked[-1]
    kids = psutil.Process(family.pid).children()
    w.refresh()
    w.select(family.pid)
    QTest.keyClick(w.view, Qt.Key.Key_Delete, Qt.KeyboardModifier.ShiftModifier)
    family.wait(5)
    time.sleep(0.3)
    assert all(not psutil.pid_exists(k.pid) or psutil.Process(k.pid).status() == psutil.STATUS_ZOMBIE for k in kids)
    assert "everything it started" in asked[-1]
    gone = w.model.proc(w.model.row_of(family.pid))
    assert gone is not None and gone.kind == "ending"                     # red for a moment


def test_suspend_resume_and_a_refusal(window, spawn):
    w = window
    w.sampler.highlight = 0                      # past the "new" highlight (it outranks suspended, as in Process Explorer)
    p = spawn()
    w.refresh()
    w.select(p.pid)
    w.suspend_resume()
    assert psutil.Process(p.pid).status() == psutil.STATUS_STOPPED and w.current().kind == "suspended"
    w.suspend_resume()
    assert psutil.Process(p.pid).status() != psutil.STATUS_STOPPED
    w.answers["confirm"] = lambda text: False                            # "no": nothing happens
    w.select(p.pid)
    assert not w.kill() and p.poll() is None


def test_lower_pane_properties_and_find(window, spawn, tmp_path):
    w = window
    f = tmp_path / "pr7sm-find-me.txt"
    holder = spawn(f"f = open({str(f)!r}, 'w')\n" + SLEEPER)
    w.refresh()
    w.select(holder.pid)
    w.load_pane()
    assert w.pane_model.rows and any("libc" in r.name or ".dll" in r.name.lower() for r in w.pane_model.rows)
    assert f"PID {holder.pid}" in w.pane_note.text()
    w.pane_tabs.setCurrentIndex(1)
    assert any(r.path == str(f) for r in w.pane_model.rows)
    w.answers["properties"] = lambda d: None
    d = w.properties()
    assert "pr7sm-find-me" in d.fields["COMMAND LINE"].text() and str(os.getpid()) in d.fields["PARENT"].text()
    w.refresh()
    d.tick()
    assert d.graphs["cpu"].values and d.graphs["private"].value
    d.close()
    w.answers["find"] = lambda d: None
    fd = w.find()
    fd.text.setText("pr7sm-find-me")
    fd.search()
    assert [(r.pid, r.kind) for r in fd.results] == [(holder.pid, "File")]
    w.select(os.getpid())
    fd._go(fd.model.index(0, 0))
    assert w.current_pid() == holder.pid


def test_system_information_and_the_menus(window):
    w = window
    w.refresh(); w.refresh()
    w.answers["system"] = lambda d: None
    d = w.system_info()
    d.tick()
    big, note, graph = d.rows["cpu"]
    assert big.text().endswith("%") and "cores" in note.text() and len(graph.values) >= 2
    assert len(d.cores) == len(w.sampler.core_history) and d.cores[0].values
    d.close()
    w.select(os.getpid())
    texts = [a.text() for a in w.row_menu().actions() if a.text()]
    assert texts[:4] == ["Properties", "Kill process", "Kill process tree", "Suspend"]
    assert "Options" in [a.text() for a in w.main_menu().actions()]


def test_options_change_the_refresh(window):
    w = window
    w.answers["options"] = lambda d: (d.refresh.setCurrentIndex(d.refresh.findData(2000)), True)[-1]
    w.options()
    assert w.timer.interval() == 2000


def test_version_and_selftest(tmp_path, capsys):
    import json
    import subprocess
    import sys
    from pr7sm import __version__, app
    assert app.main(["--version"]) == 0 and capsys.readouterr().out.strip() == __version__
    out = tmp_path / "out.json"
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = subprocess.run([sys.executable, "-m", "pr7sm", "--selftest", str(out)], cwd=root, timeout=120).returncode
    got = json.loads(out.read_text())
    assert code == 0, got
    assert got["found_child"] and got["child_under_me"] and got["suspended"] and got["resumed"] and got["killed"]
    assert got["processes"] > 3 and got["dlls"] > 0 and got["physical_total"] > 0 and got["fonts"]


def test_replacing_task_manager_writes_nothing_off_windows():
    from pr7sm import app, taskmgr
    assert not taskmgr.available() or os.name == "nt"
    if os.name != "nt":
        assert taskmgr.run("--replace-taskmgr") == 1 and app.main(["--uninstall"]) == 0
    assert taskmgr.is_ours('"C:\\Users\\me\\AppData\\Local\\Programs\\PR7-SM\\PR7-SM.exe" /taskmgr')
    assert not taskmgr.is_ours('"C:\\Tools\\procexp64.exe" /e')                # Process Explorer's: never ours
