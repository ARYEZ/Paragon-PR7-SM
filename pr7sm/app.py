"""Start PR7-SM.

    PR7-SM.exe                      the window (one per user: a second start brings the first to the front)
    PR7-SM.exe /taskmgr ...         the same, started by Windows in Task Manager's place (Replace Task Manager)
    PR7-SM.exe --replace-taskmgr    set the redirect (administrator: the elevated helper Options runs)
    PR7-SM.exe --restore-taskmgr    take PR7-SM's redirect away (administrator)
    PR7-SM.exe --uninstall          the uninstaller: puts Task Manager back, asking for rights only if it was replaced
    PR7-SM.exe --version
    PR7-SM.exe --selftest OUT.json  sample the real system, start a process, find it in the tree, suspend, resume and
                                    end it, and write what happened (CI checks the installed exe)
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import sys

TIMEOUT_MS = 1500


def server_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "user"
    return "Paragon-PR7-SM-" + hashlib.sha1(user.encode()).hexdigest()[:12]


def hand_over() -> bool:
    from PySide6.QtNetwork import QLocalSocket
    s = QLocalSocket()
    s.connectToServer(server_name())
    if not s.waitForConnected(TIMEOUT_MS):
        return False
    s.write(b'{"show": true}\n')
    s.flush()
    s.waitForBytesWritten(TIMEOUT_MS)
    if not s.waitForDisconnected(TIMEOUT_MS):
        s.disconnectFromServer()
    return True


def listen(window):
    """Later starts bring this window to the front (PR7-R's hand-off, with its Windows fix)."""
    from PySide6.QtNetwork import QLocalServer
    server = QLocalServer(window)
    QLocalServer.removeServer(server_name())
    if not server.listen(server_name()):
        return None

    def connection():
        sock = server.nextPendingConnection()
        if sock is None:
            return
        done = []

        def read():
            if not done and bytes(sock.readAll()).strip():
                done.append(True)
                window.showNormal()
                window.raise_()
                window.activateWindow()
                sock.disconnectFromServer()
        sock.readyRead.connect(read)
        if sock.bytesAvailable():
            read()
    server.newConnection.connect(connection)
    window.instance_server = server
    return server


def selftest(out: str) -> int:
    import subprocess
    import tempfile
    import time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PR7SM_DATA"] = tempfile.mkdtemp()
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tempfile.mkdtemp())
    app = QApplication.instance() or QApplication(sys.argv[:1])
    result = {}
    child = None
    try:
        import psutil
        from . import __version__, actions, theme
        from .main_window import MainWindow
        theme.load_fonts()
        w = MainWindow()
        w.timer.stop()
        w.sync = True
        w.answers.update({"say": lambda k, t: None, "menu": lambda *a: None, "confirm": lambda t: True})
        # a child to act on: ping waits on Windows, sleep elsewhere; it's ours, so no rights are needed
        cmd = ["ping", "-n", "60", "127.0.0.1"] if sys.platform == "win32" else ["sleep", "60"]
        child = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=0x08000000 if sys.platform == "win32" else 0)   # CREATE_NO_WINDOW
        time.sleep(0.5)
        w.refresh()
        time.sleep(1.0)
        w.refresh()
        snap = w.sampler.snapshot
        me = snap.procs.get(os.getpid())
        found = w.select(child.pid)
        under_me = me is not None and child.pid in me.children
        w.suspend_resume()
        suspended = psutil.Process(child.pid).status() == psutil.STATUS_STOPPED
        w.suspend_resume()
        resumed = psutil.Process(child.pid).status() != psutil.STATUS_STOPPED
        w.load_pane()
        dlls = len(w.pane_model.rows)
        killed = w.kill()
        try:
            child.wait(5)
        except subprocess.TimeoutExpired:
            pass
        t = snap.totals
        names = {p.name.casefold() for p in snap.procs.values()}
        result = {"version": __version__, "processes": len(snap.procs), "found_child": found,
                  "child_under_me": under_me, "suspended": suspended, "resumed": resumed, "dlls": dlls,
                  "killed": bool(killed) and child.poll() is not None,
                  "described": sum(1 for p in snap.procs.values() if p.description),
                  "system_seen": any(n in names for n in ("system", "explorer.exe", "systemd", "init")),
                  "cpu": round(t.cpu, 1), "physical_total": t.physical_total, "commit_limit": t.commit_limit,
                  "fonts": "Inter" in QFontDatabase.families(), "admin": actions is not None and
                  __import__("pr7sm.procs", fromlist=["is_admin"]).is_admin()}
        w.close()
    except Exception as e:  # noqa: BLE001 - reported in the output
        result = {"error": f"{type(e).__name__}: {e}"}
    finally:
        if child is not None and child.poll() is None:
            child.kill()
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh)
    return 0 if result.get("killed") else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or not argv[0].startswith("--"):
        return _window(argv)
    # a command-line mode (the installer, CI, the elevated helper): an unexpected error must end the process with a
    # code; in the windowed exe it would otherwise open an error box that waits for a click nobody gives
    try:
        return _command(argv)
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001 - reported, then a failing exit code
        import traceback
        if sys.stderr is not None:
            sys.stderr.write(traceback.format_exc())
        return 2


def _command(argv: list[str]) -> int:
    from . import taskmgr
    if argv[:1] == ["--version"]:
        from . import __version__
        print(__version__)
        return 0
    if argv[:1] == ["--selftest"] and len(argv) == 2:
        return selftest(argv[1])
    if argv[:1] in (["--replace-taskmgr"], ["--restore-taskmgr"]):
        return taskmgr.run(argv[0])
    if argv[:1] == ["--uninstall"]:
        if taskmgr.available() and taskmgr.is_replaced():
            try:
                taskmgr.restore()
            except PermissionError:
                taskmgr.run_elevated("--restore-taskmgr")
        return 0
    print(__doc__)
    return 1


def _window(argv: list[str]) -> int:
    from PySide6.QtWidgets import QApplication

    from . import settings, theme
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setOrganizationName("Paragon")
    app.setApplicationName("PR7-SM")
    if hand_over():
        return 0
    from . import finish
    theme.set_finish(finish.start(settings.get("finish", "obsidian")))
    theme.load_fonts()
    app.setPalette(theme.palette())
    from PySide6.QtGui import QIcon
    icon = os.path.join(os.path.dirname(__file__), "icons", "app.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    from .main_window import MainWindow
    w = MainWindow()
    # one finish for the family: follow a switch made in another family app (finish.py)
    from PySide6.QtCore import QTimer
    _follow = QTimer(w)
    _follow.timeout.connect(lambda: finish.follow(theme.FINISH, w.set_finish))
    _follow.start(2000)
    listen(w)
    w.show()
    from . import update_ui
    update_ui.start(w)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
