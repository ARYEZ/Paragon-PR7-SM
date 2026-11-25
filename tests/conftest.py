import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PARAGON_FAMILY_FILE"] = os.path.join(__import__("tempfile").mkdtemp(prefix="family-"), "finish")  # never the real choice
os.environ["PR7SM_DATA"] = tempfile.mkdtemp()                    # never the real data folder

SLEEPER = "import time\nwhile True: time.sleep(0.2)"
BUSY = "while True: pass"


@pytest.fixture
def spawn():
    """Real child processes (python itself), ended afterwards whatever the test did to them."""
    made = []

    def make(code=SLEEPER, *args):
        p = subprocess.Popen([sys.executable, "-c", code, *args])
        made.append(p)
        time.sleep(0.3)
        return p
    yield make
    for p in made:
        try:
            import psutil
            for c in psutil.Process(p.pid).children(recursive=True):
                c.kill()
        except Exception:
            pass
        p.kill()
        p.wait(5)


@pytest.fixture(scope="session")
def qapp(tmp_path_factory):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)           # never the real settings
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path_factory.mktemp("settings")))
    app = QApplication.instance() or QApplication([])
    from pr7sm import theme
    theme.load_fonts()
    yield app
    app.clipboard().clear()                  # PySide's offscreen clipboard crashes at exit while it holds data


@pytest.fixture
def window(qapp):
    from pr7sm import main_window, settings
    for k in ("refresh_ms", "highlight_s", "confirm_kill", "lower_pane"):
        settings.set(k, main_window.DEFAULTS[k])
    w = main_window.MainWindow()
    w.timer.stop()                                  # tests refresh by hand: no timing in the results
    w.sync = True
    w.answers.update({"say": lambda kind, text: None, "menu": lambda *a: None})
    w.show()
    yield w
    w.close()
