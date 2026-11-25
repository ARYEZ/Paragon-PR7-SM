"""PR7-SM's window, the way Process Explorer's works: the process tree (refreshed every second, coloured by kind),
mini graphs, the lower pane (DLLs / handles of the selected process), Properties, System Information, Find Handle or
DLL, and the actions (kill, kill tree, suspend, priority) with Process Explorer's keys.

The tree is a flat list where each row knows its depth: a refresh that keeps the same processes only says "values
changed", so the selection, the scroll position and collapsed branches never jump. Clicking a column sorts the list
flat; clicking it a third time goes back to the tree (Process Explorer does the same). Every question goes through
`_ask(kind, ...)`: tests answer them with `window.answers[kind]`."""

from __future__ import annotations

import os
import sys
import threading
import time

from PySide6.QtCore import (QAbstractTableModel, QEvent, QModelIndex, QObject, QPointF, QRectF, QSize, Qt, QTimer,
                            Signal)
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFileIconProvider,
                               QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu,
                               QMessageBox, QPushButton, QSplitter, QStackedWidget, QStyle, QStyledItemDelegate,
                               QTabBar, QTableView, QTreeView, QVBoxLayout, QWidget)

from . import __version__, actions, family, finish, procs, settings, taskmgr, theme, widgets
from .graphs import Graph

COLUMNS = ["PROCESS", "CPU", "PRIVATE BYTES", "WORKING SET", "PID", "DESCRIPTION", "COMPANY NAME"]
RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
# Process Explorer's row colours, in the family's: services pink, your own processes orange, new pearl, ending red,
# suspended onyx.
KIND = {"service": "#E0457B", "own": "#F07A2A", "new": "#E8E2E6", "ending": "#F4353A", "suspended": "#55505A"}
LEGEND = [("service", "SERVICES"), ("own", "YOUR PROCESSES"), ("new", "NEW"), ("ending", "ENDING"),
          ("suspended", "SUSPENDED")]
DEFAULTS = {"refresh_ms": 1000, "highlight_s": 2, "confirm_kill": True, "lower_pane": True}
TINT_ROLE = Qt.ItemDataRole.UserRole + 1
DEPTH_ROLE = Qt.ItemDataRole.UserRole + 2
INDENT = 16


def option(key):
    d = DEFAULTS[key]
    return settings.get_bool(key, d) if isinstance(d, bool) else settings.get_int(key, d)


def tint(kind: str) -> QColor | None:
    if not kind:
        return None
    if kind == "new" and theme.FINISH == "aurora":     # pearl vanishes on the light finish: a deeper grey there
        c = QColor("#8F8489")
        c.setAlphaF(.35)
        return c
    c = QColor(KIND[kind])
    c.setAlphaF(.5 if kind == "suspended" else .22)
    return c


def cpu_text(v) -> str:
    """Process Explorer's CPU column: blank for none, < 0.01 for a little."""
    if v is None or v <= 0:
        return ""
    return "< 0.01" if v < 0.01 else f"{v:.2f}"


def stylesheet() -> str:
    return theme.stylesheet() + f"""
QTableView::item:selected, QTreeView::item:selected {{ background: {theme.ACCENT_DIM}; color: #FFFFFF; }}
QTableView {{ alternate-background-color: {theme.ALT_ROW}; }}
QLabel#key {{ color: {theme.TEXT_DIM}; font-size: 11px; font-weight: 600; letter-spacing: 1px; }}
QLabel#big {{ font-size: 22px; font-weight: 600; }}
QLabel#note {{ color: {theme.TEXT_DIM}; }}
QLabel#value {{ font-size: 13px; }}
QPushButton[kind="primary"] {{ background: {theme.qss_gradient()}; color: #FFFFFF; border: none; border-radius: 4px;
    padding: 9px 22px; font-weight: 600; }}
QFrame#pane {{ background: {theme.DOCK_TOP}; border-top: 1px solid {theme.PANEL_EDGE}; }}
"""


def keyed(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("key")
    return lab


# ======================================================================== the process list
class ProcModel(QAbstractTableModel):
    """The shown rows (pids, in tree order or sorted), from the latest snapshot. A plain Python list (never
    QStandardItemModel: its item ownership crashed PySide in PR7-Z)."""

    def __init__(self):
        super().__init__()
        self.snap: procs.Snapshot | None = None
        self.rows: list[int] = []
        self.collapsed: set[int] = set()
        self.sort: tuple[int, bool] | None = None      # (column, descending); None = the tree
        self.filter = ""
        self.icons = QFileIconProvider()
        self._icon_cache: dict[str, object] = {}

    def update(self, snap: procs.Snapshot) -> bool:
        """New values; True when the rows themselves changed (a reset), False when only their values did."""
        self.snap = snap
        rows = self._rows()
        if rows == self.rows:
            if rows:
                self.dataChanged.emit(self.index(0, 0), self.index(len(rows) - 1, len(COLUMNS) - 1))
            return False
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()
        return True

    def _rows(self) -> list[int]:
        s = self.snap
        if s is None:
            return []
        if self.filter:
            f = self.filter.casefold()
            return sorted((pid for pid, p in s.procs.items()
                           if f in p.name.casefold() or f in p.description.casefold() or f == str(pid)),
                          key=lambda pid: (s.procs[pid].name.casefold(), pid))
        if self.sort is not None:
            col, desc = self.sort
            return sorted(s.procs, key=lambda pid: self._key(s.procs[pid], col), reverse=desc)
        out, hidden_below = [], None
        for pid in s.order:
            p = s.procs[pid]
            if hidden_below is not None:
                if p.depth > hidden_below:
                    continue
                hidden_below = None
            out.append(pid)
            if pid in self.collapsed and p.children:
                hidden_below = p.depth
        return out

    @staticmethod
    def _key(p: procs.Proc, col: int):
        return [(p.name.casefold(), p.pid), (p.cpu or 0.0, p.pid), (p.private, p.pid), (p.working, p.pid),
                (p.pid,), (p.description.casefold(), p.pid), (p.company.casefold(), p.pid)][col]

    def proc(self, row: int) -> procs.Proc | None:
        if self.snap is None or not 0 <= row < len(self.rows):
            return None
        return self.snap.procs.get(self.rows[row])

    def row_of(self, pid: int) -> int:
        try:
            return self.rows.index(pid)
        except ValueError:
            return -1

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            arrow = ""
            if self.sort is not None and self.sort[0] == section:
                arrow = "  ▼" if self.sort[1] else "  ▲"
            return COLUMNS[section] + arrow
        if role == Qt.ItemDataRole.TextAlignmentRole and 1 <= section <= 4:
            return RIGHT
        return None

    def _icon(self, p: procs.Proc):
        key = p.exe.casefold() if p.exe else ""
        if key not in self._icon_cache:
            icon = None
            if p.exe and sys.platform == "win32":
                from PySide6.QtCore import QFileInfo
                icon = self.icons.icon(QFileInfo(p.exe))
            if icon is None or icon.isNull():
                icon = widgets.line_icon("app" if p.exe else "chart", theme.TEXT_DIM, 16)
            self._icon_cache[key] = icon
        return self._icon_cache[key]

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        p = self.proc(index.row())
        if p is None:
            return None
        c = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if c == 0:
                return p.name
            if c == 1:
                return cpu_text(p.cpu)
            if c == 2:
                return procs.human(p.private) if p.private else ""
            if c == 3:
                return procs.human(p.working) if p.working else ""
            if c == 4:
                return str(p.pid)
            return p.description if c == 5 else p.company
        if role == Qt.ItemDataRole.TextAlignmentRole and 1 <= c <= 4:
            return RIGHT
        if role == Qt.ItemDataRole.DecorationRole and c == 0:
            return self._icon(p)
        if role == TINT_ROLE:
            return tint(p.kind)
        if role == DEPTH_ROLE:
            return p.depth if self.sort is None and not self.filter else 0
        if role == Qt.ItemDataRole.ToolTipRole and c == 0:
            return p.exe or p.name
        if role == Qt.ItemDataRole.ForegroundRole and p.kind == "ending":
            return QColor("#FFB4B6")
        return None


class RowDelegate(QStyledItemDelegate):
    """The row's colour first (the theme's ::item rules make Qt ignore an item's own background), then for the PROCESS
    column the tree's indent and its arrow, then the normal row on top."""

    def __init__(self, view, model: ProcModel):
        super().__init__(view)
        self.model = model

    def paint(self, p, option, index):
        c = index.data(TINT_ROLE)
        if c is not None:
            p.fillRect(option.rect, c)
        if index.column() == 0:
            depth = index.data(DEPTH_ROLE) or 0
            pr = self.model.proc(index.row())
            arrow_w = 14
            x = option.rect.left() + depth * INDENT
            if pr is not None and pr.children and self.model.sort is None and not self.model.filter:
                p.save()
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setPen(QPen(QColor(theme.TEXT_DIM), 1.4))
                cy, cx = option.rect.center().y(), x + 6
                path = QPainterPath()
                if pr.pid in self.model.collapsed:
                    path.moveTo(cx - 2, cy - 4); path.lineTo(cx + 2, cy); path.lineTo(cx - 2, cy + 4)
                else:
                    path.moveTo(cx - 4, cy - 2); path.lineTo(cx, cy + 2); path.lineTo(cx + 4, cy - 2)
                p.drawPath(path)
                p.restore()
            option.rect.setLeft(x + arrow_w)
        super().paint(p, option, index)

    def arrow_hit(self, index, pos) -> bool:
        if index.column() != 0:
            return False
        rect = self.parent().visualRect(index)
        x = rect.left() + (index.data(DEPTH_ROLE) or 0) * INDENT
        return x <= pos.x() <= x + 14


class ProcView(QTreeView):
    """The process list takes Process Explorer's keys itself (window shortcuts need an active window)."""

    def __init__(self, window):
        super().__init__()
        self.window = window

    def keyPressEvent(self, e):
        w = self.window
        k, mods = e.key(), e.modifiers()
        if k == Qt.Key.Key_Delete:
            (w.kill_tree if mods & Qt.KeyboardModifier.ShiftModifier else w.kill)()
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            w.properties()
        elif k == Qt.Key.Key_Space:
            w.toggle_pause()
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_Right) and w.model.sort is None and not w.model.filter:
            p = w.current()
            if p is not None and p.children:
                w.set_collapsed(p.pid, k == Qt.Key.Key_Left)
        else:
            super().keyPressEvent(e)

    def mousePressEvent(self, e):
        idx = self.indexAt(e.position().toPoint())
        if idx.isValid() and self.itemDelegate().arrow_hit(idx, e.position().toPoint()):
            p = self.window.model.proc(idx.row())
            if p is not None and p.children:
                self.window.set_collapsed(p.pid, p.pid not in self.window.model.collapsed)
                return
        super().mousePressEvent(e)


class PaneModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self.rows: list[actions.Row] = []
        self.headers = ["NAME", "DESCRIPTION", "COMPANY NAME", "PATH"]

    def set_rows(self, rows, headers=None):
        self.beginResetModel()
        self.rows = list(rows)
        if headers:
            self.headers = headers
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 4

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole or not index.isValid():
            return None
        r = self.rows[index.row()]
        return [r.name, r.description, r.company, r.path][index.column()]


class _Bridge(QObject):
    pane = Signal(int, str, object)              # pid, tab, rows or a Problem
    found = Signal(object)


# ======================================================================== the window
class MainWindow(QMainWindow):
    updated = Signal()

    def __init__(self, sampler: procs.Sampler | None = None):
        super().__init__()
        self.setWindowTitle("Paragon PR7-SM")
        self.resize(1280, 900)
        self.answers: dict = {}
        self.said: list = []
        self.sync = False                            # tests: the lower pane and Find run inline
        self.sampler = sampler or procs.Sampler(highlight=option("highlight_s"))
        self.paused = False
        self.bridge = _Bridge()
        self.bridge.pane.connect(self._pane_loaded)
        self.dialogs: list[QDialog] = []
        body = QWidget()
        self.setCentralWidget(body)
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.header = widgets.Header("SYSTEM")
        v.addWidget(self.header)
        v.addLayout(self._toolbar())
        split = QSplitter(Qt.Orientation.Vertical)
        split.setChildrenCollapsible(False)
        self.model = ProcModel()
        self.view = ProcView(self)
        self.view.setModel(self.model)
        self.view.setRootIsDecorated(False)
        self.view.setUniformRowHeights(True)
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.setIconSize(QSize(16, 16))
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.view.setItemDelegate(RowDelegate(self.view, self.model))
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(lambda pos: self.row_menu(self.view.viewport().mapToGlobal(pos)))
        self.view.doubleClicked.connect(lambda _: self.properties())
        h = self.view.header()
        h.setSectionsClickable(True)
        h.sectionClicked.connect(self.sort_by)
        for c, w in ((0, 260), (1, 70), (2, 120), (3, 120), (4, 70), (5, 300)):
            h.resizeSection(c, w)
        h.setStretchLastSection(True)
        self.view.selectionModel().currentRowChanged.connect(lambda *_: self.load_pane())
        split.addWidget(self.view)
        split.addWidget(self._pane())
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        v.addWidget(split, 1)
        v.addLayout(self._status())
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.restyle()
        self.refresh()
        self.timer.start(option("refresh_ms"))
        self.pane.setVisible(option("lower_pane"))

    def restyle(self):
        QApplication.instance().setPalette(theme.palette())
        self.setStyleSheet(stylesheet())
        self.header.update()

    def set_finish(self, name: str):
        """OBSIDIAN or AURORA, for this window, its open dialogs and (finish.py) every other family app."""
        theme.set_finish(name)
        finish.set(theme.FINISH)                 # every family app follows (finish.py)
        settings.set("finish", theme.FINISH)
        self.restyle()
        self.model._icon_cache.clear()           # the line icons are drawn in the finish's colours
        for d in self.dialogs:
            d.setStyleSheet(stylesheet())
            if hasattr(d, "header"):
                d.header.update()
        self.update()

    # ---------------------------------------------------------------- parts
    def _toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setContentsMargins(14, 10, 14, 10)
        bar.setSpacing(4)
        self.pause_key = None
        for item in (("refresh", "Refresh now (F5)", self.refresh), ("pause", "Pause updates (Space)", self.toggle_pause),
                     None, ("info", "Properties (Enter)", self.properties), ("close", "Kill process (Del)", self.kill),
                     ("search", "Find a handle or DLL (Ctrl+F)", self.find), None,
                     ("chart", "System information (Ctrl+I)", self.system_info)):
            if item is None:
                bar.addSpacing(14)
                continue
            k = widgets.SmallKey(item[0], item[1], checkable=item[0] == "pause")
            k.clicked.connect(item[2])
            if item[0] == "pause":
                self.pause_key = k
            bar.addWidget(k)
        bar.addSpacing(18)
        self.mini = {}
        for key, label in (("cpu", "CPU"), ("memory", "MEMORY"), ("io", "I/O")):
            g = Graph(label, small=True)
            g.setFixedSize(150, 40)
            g.setCursor(Qt.CursorShape.PointingHandCursor)
            g.mousePressEvent = lambda e: self.system_info()
            self.mini[key] = g
            bar.addWidget(g)
        bar.addStretch(1)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter by name")
        self.filter.setFixedWidth(260)
        self.filter.textChanged.connect(self._filter_changed)
        bar.addWidget(self.filter)
        more = widgets.SmallKey("more", "Menu")
        more.clicked.connect(self.show_menu)
        bar.addWidget(more)
        for keys, slot in (("F5", self.refresh), ("Ctrl+F", self.find), ("Ctrl+I", self.system_info),
                           ("Ctrl+L", lambda: self.filter.setFocus())):
            a = QAction(self)
            a.setShortcut(QKeySequence(keys))
            a.triggered.connect(slot)
            self.addAction(a)
        return bar

    def _pane(self) -> QFrame:
        self.pane = QFrame()
        self.pane.setObjectName("pane")
        pv = QVBoxLayout(self.pane)
        pv.setContentsMargins(0, 6, 0, 0)
        pv.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(14, 0, 14, 4)
        self.pane_tabs = QTabBar()
        self.pane_tabs.addTab("DLLS")
        self.pane_tabs.addTab("HANDLES")
        self.pane_tabs.setExpanding(False)
        self.pane_tabs.currentChanged.connect(lambda _: self.load_pane())
        row.addWidget(self.pane_tabs)
        row.addStretch(1)
        self.pane_note = QLabel("")
        self.pane_note.setObjectName("note")
        row.addWidget(self.pane_note)
        pv.addLayout(row)
        self.pane_model = PaneModel()
        t = QTableView()
        t.setModel(self.pane_model)
        t.verticalHeader().hide()
        t.setShowGrid(False)
        t.setAlternatingRowColors(True)
        t.setFrameShape(QFrame.Shape.NoFrame)
        t.verticalHeader().setDefaultSectionSize(25)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for c, w in ((0, 200), (1, 300), (2, 200)):
            t.setColumnWidth(c, w)
        t.horizontalHeader().setStretchLastSection(True)
        self.pane_table = t
        pv.addWidget(t)
        return self.pane

    def _status(self) -> QHBoxLayout:
        st = QHBoxLayout()
        st.setContentsMargins(14, 7, 14, 7)
        self.status = QLabel("")
        self.status.setObjectName("note")
        st.addWidget(self.status)
        st.addStretch(1)
        for kind, label in LEGEND:
            sw = QLabel()
            sw.setFixedSize(10, 10)
            sw.setStyleSheet(f"background: {KIND[kind]}; border-radius: 2px;")
            st.addWidget(sw)
            st.addSpacing(5)
            st.addWidget(keyed(label))
            st.addSpacing(8)
        return st

    # ---------------------------------------------------------------- refreshing
    def refresh(self):
        keep = self.current_pid()
        bar = self.view.verticalScrollBar().value()
        snap = self.sampler.sample()
        if self.model.update(snap):
            if keep is not None and self.model.row_of(keep) >= 0:
                self.select(keep, scroll=False)
            self.view.verticalScrollBar().setValue(bar)
        t, h = snap.totals, self.sampler.history
        self.mini["cpu"].set_data(h["cpu"], f"{t.cpu:.1f}%", h["kernel"])
        self.mini["memory"].set_data(h["physical"], f"{100 * t.physical / max(1, t.physical_total):.0f}%")
        self.mini["io"].set_data([r + w for r, w in zip(h["read"], h["write"])], procs.rate(t.read + t.write),
                                 h["write"], top=None)
        self.status.setText(
            f"CPU {t.cpu:.1f}%      Commit {procs.human(t.commit)} of {procs.human(t.commit_limit)} "
            f"({100 * t.commit / max(1, t.commit_limit):.0f}%)      "
            f"Physical memory {100 * t.physical / max(1, t.physical_total):.0f}%      Processes {t.processes}")
        self.updated.emit()

    def toggle_pause(self):
        self.paused = not self.paused
        if self.paused:
            self.timer.stop()
        else:
            self.timer.start(option("refresh_ms"))
        if self.pause_key is not None:
            self.pause_key.setChecked(self.paused)

    def sort_by(self, col: int):
        """Click a column: sorted by it (ascending, then descending), then back to the tree."""
        s = self.model.sort
        if s is None or s[0] != col:
            desc = col in (1, 2, 3)                   # the busiest first for CPU and memory, as Process Explorer
            self.model.sort = (col, desc)
        elif s[1] == (col in (1, 2, 3)):
            self.model.sort = (col, not s[1])
        else:
            self.model.sort = None
        keep = self.current_pid()
        self.model.update(self.sampler.snapshot)
        self.model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(COLUMNS) - 1)
        if keep is not None:
            self.select(keep)

    def _filter_changed(self, text: str):
        self.model.filter = text.strip()
        keep = self.current_pid()
        self.model.update(self.sampler.snapshot)
        if keep is not None and self.model.row_of(keep) >= 0:
            self.select(keep)

    def set_collapsed(self, pid: int, collapsed: bool):
        (self.model.collapsed.add if collapsed else self.model.collapsed.discard)(pid)
        self.model.update(self.sampler.snapshot)
        self.select(pid)

    def current_pid(self) -> int | None:
        p = self.current()
        return p.pid if p is not None else None

    def current(self) -> procs.Proc | None:
        idx = self.view.currentIndex()
        return self.model.proc(idx.row()) if idx.isValid() else None

    def select(self, pid: int, scroll: bool = True) -> bool:
        row = self.model.row_of(pid)
        if row < 0:
            return False
        idx = self.model.index(row, 0)
        self.view.setCurrentIndex(idx)
        if scroll:
            self.view.scrollTo(idx)
        return True

    # ---------------------------------------------------------------- the lower pane
    def load_pane(self):
        p = self.current()
        if p is None or not self.pane.isVisible() and not self.sync:
            self.pane_model.set_rows([])
            self.pane_note.setText("")
            return
        tab = "handles" if self.pane_tabs.currentIndex() == 1 else "dlls"
        pid = p.pid

        def work():
            try:
                rows = (actions.handles if tab == "handles" else actions.dlls)(pid)
            except actions.Problem as e:
                rows = e
            self.bridge.pane.emit(pid, tab, rows)
        if self.sync:
            work()
        else:
            threading.Thread(target=work, daemon=True).start()

    def _pane_loaded(self, pid: int, tab: str, rows):
        p = self.current()
        if p is None or p.pid != pid:
            return                                    # the selection moved on meanwhile
        if isinstance(rows, actions.Problem):
            self.pane_model.set_rows([])
            self.pane_note.setText(str(rows))
            return
        heads = ["NAME", "DESCRIPTION", "COMPANY NAME", "PATH"] if tab == "dlls" else ["NAME", "STATE", "", "PATH"]
        self.pane_model.set_rows(rows, heads)
        self.pane_note.setText(f"{p.name}  ·  PID {pid}  ·  {len(rows):,} {'DLLs' if tab == 'dlls' else 'handles'}")

    # ---------------------------------------------------------------- actions
    def _act(self, fn, *args) -> bool:
        try:
            fn(*args)
        except actions.Problem as e:
            self._say("warning", str(e))
            return False
        self.refresh()
        return True

    def kill(self):
        p = self.current()
        if p is None or p.gone:
            return False
        if option("confirm_kill") and not self._ask("confirm", f"End {p.name} ({p.pid})? Anything it hasn't saved is "
                                                               "lost."):
            return False
        return self._act(actions.kill, p.pid)

    def kill_tree(self):
        p = self.current()
        if p is None or p.gone:
            return False
        if option("confirm_kill") and not self._ask("confirm", f"End {p.name} ({p.pid}) and everything it started? "
                                                               "Anything they haven't saved is lost."):
            return False
        return self._act(actions.kill_tree, p.pid)

    def suspend_resume(self):
        p = self.current()
        if p is not None and not p.gone:
            self._act(actions.resume if p.kind == "suspended" or p.status == "stopped" else actions.suspend, p.pid)

    def set_priority(self, name: str):
        p = self.current()
        if p is not None:
            self._act(actions.set_priority, p.pid, name)

    def open_folder(self, path: str | None = None):
        path = path or (self.current().exe if self.current() else "")
        if not path:
            return
        folder = os.path.dirname(path)
        launch = self.answers.get("launch", family.launch)
        if launch("PR7-E", [folder]):
            return
        if sys.platform == "win32":
            import subprocess
            subprocess.Popen(["explorer", "/select,", path])   # noqa: S603,S607 - Explorer at the file

    def copy(self, text: str):
        QApplication.clipboard().setText(text)

    def row_menu(self, at=None) -> QMenu:
        p = self.current()
        m = QMenu(self)
        if p is None:
            return m
        m.addAction("Properties", self.properties)
        m.addSeparator()
        m.addAction("Kill process", self.kill).setShortcut(QKeySequence("Del"))
        m.addAction("Kill process tree", self.kill_tree).setShortcut(QKeySequence("Shift+Del"))
        m.addAction("Resume" if p.kind == "suspended" else "Suspend", self.suspend_resume)
        pri = m.addMenu("Set priority")
        now = actions.priority(p.pid)
        for name in actions.PRIORITIES:
            a = pri.addAction(name, lambda n=name: self.set_priority(n))
            a.setCheckable(True)
            a.setChecked(name == now)
        m.addSeparator()
        m.addAction("Open folder", self.open_folder).setEnabled(bool(p.exe))
        m.addAction("Copy path", lambda: self.copy(p.exe)).setEnabled(bool(p.exe))
        m.addAction("Copy PID", lambda: self.copy(str(p.pid)))
        for a in m.actions():
            a.setEnabled(a.isEnabled() and not p.gone)
        if at is not None and "menu" not in self.answers:
            m.exec(at)
        return m

    def show_menu(self):
        m = self.main_menu()
        if "menu" not in self.answers:
            m.exec(self.cursor().pos())

    def main_menu(self) -> QMenu:
        m = QMenu(self)
        m.addAction("System information", self.system_info)
        m.addAction("Find a handle or DLL", self.find)
        m.addSeparator()
        a = m.addAction("Show the lower pane", lambda: self.show_pane(not self.pane.isVisible()))
        a.setCheckable(True)
        a.setChecked(self.pane.isVisible())
        if sys.platform == "win32" and not procs.is_admin():
            m.addAction("Show details for all processes (run as administrator)", self.run_as_admin)
        fin = m.addMenu("Finish")
        for name in ("obsidian", "aurora"):
            a = fin.addAction(name.upper(), lambda n=name: self.set_finish(n))
            a.setCheckable(True)
            a.setChecked(theme.FINISH == name)
        m.addAction("Options", self.options)
        m.addAction("Check for updates", self.check_updates)
        m.addAction(f"About PR7-SM {__version__}", lambda: self._say(
            "info", f"Paragon PR7-SM {__version__}: a system monitor that works the way Process Explorer works."))
        return m

    def show_pane(self, on: bool):
        self.pane.setVisible(on)
        settings.set("lower_pane", on)
        if on:
            self.load_pane()

    def run_as_admin(self):
        if taskmgr.restart_as_admin():
            self.close()

    def check_updates(self):
        from . import update_ui
        update_ui.check(self, manual=True)

    # ---------------------------------------------------------------- windows of their own
    def properties(self):
        p = self.current()
        if p is None or p.gone:
            return None
        try:
            d = PropertiesDialog(self, p.pid)
        except actions.Problem as e:
            self._say("warning", str(e))
            return None
        self._show(d, "properties")
        return d

    def system_info(self):
        d = SystemInfoDialog(self)
        self._show(d, "system")
        return d

    def find(self):
        d = FindDialog(self)
        self._show(d, "find")
        return d

    def options(self):
        d = OptionsDialog(self)
        if self._ask("options", d):
            d.save()
            self.timer.setInterval(option("refresh_ms"))
            self.sampler.highlight = option("highlight_s")

    def _show(self, d: QDialog, kind: str):
        d.setStyleSheet(stylesheet())
        self.dialogs = [x for x in self.dialogs if x.isVisible()] + [d]
        if kind in self.answers:
            self.answers[kind](d)
        else:
            d.show()

    # ---------------------------------------------------------------- questions
    def _ask(self, kind: str, payload=None):
        if kind in self.answers:
            return self.answers[kind](payload)
        if isinstance(payload, QDialog):
            payload.setStyleSheet(stylesheet())
            return payload.exec() == QDialog.DialogCode.Accepted
        if kind == "confirm":
            return QMessageBox.question(self, "Paragon PR7-SM", payload) == QMessageBox.StandardButton.Yes
        return None

    def _say(self, kind: str, text: str):
        self.said.append((kind, text))
        if "say" in self.answers:
            self.answers["say"](kind, text)
            return
        (QMessageBox.warning if kind == "warning" else QMessageBox.information)(self, "Paragon PR7-SM", text)

    def closeEvent(self, e):
        self.timer.stop()
        for d in self.dialogs:
            d.close()
        super().closeEvent(e)


# ======================================================================== Properties
class PropertiesDialog(QDialog):
    """Process Explorer's Properties: Image (with live graphs), Threads, TCP/IP, Environment."""

    def __init__(self, window: MainWindow, pid: int):
        super().__init__(window)
        self.window, self.pid = window, pid
        self.info = actions.details(pid)
        self.setWindowTitle(f"{self.info.get('name') or pid} ({pid}) - Paragon PR7-SM")
        self.resize(760, 600)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.header = widgets.Header("PROPERTIES")
        v.addWidget(self.header)
        b = QVBoxLayout()
        b.setContentsMargins(24, 16, 24, 20)
        b.setSpacing(10)
        v.addLayout(b, 1)
        self.tabs = QTabBar()
        for t in ("IMAGE", "THREADS", "TCP/IP", "ENVIRONMENT"):
            self.tabs.addTab(t)
        self.tabs.setExpanding(False)
        b.addWidget(self.tabs)
        self.pages = QStackedWidget()
        b.addWidget(self.pages, 1)
        self.pages.addWidget(self._image())
        self.pages.addWidget(self._table(["THREAD ID", "USER TIME", "KERNEL TIME"],
                                         [[str(t[0]), f"{t[1]:.2f} s", f"{t[2]:.2f} s"]
                                          for t in self.info.get("thread_list") or []]))
        self.pages.addWidget(self._table(["PROTOCOL", "ADDRESSES", "STATE"],
                                         [[r.kind, r.name.split(" ", 1)[-1], r.description]
                                          for r in self.info.get("connections") or [] if r.kind in ("TCP", "UDP")]))
        env = self.info.get("environ") or {}
        self.pages.addWidget(self._table(["VARIABLE", "VALUE"], [[k, env[k]] for k in sorted(env, key=str.casefold)]))
        self.tabs.currentChanged.connect(self.pages.setCurrentIndex)
        row = QHBoxLayout()
        self.open_button = QPushButton("OPEN FOLDER")
        self.open_button.setEnabled(bool(self.info.get("exe")))
        self.open_button.clicked.connect(lambda: window.open_folder(self.info.get("exe")))
        row.addWidget(self.open_button)
        self.suspend_button = QPushButton("SUSPEND")
        self.suspend_button.clicked.connect(self._suspend)
        row.addWidget(self.suspend_button)
        pri = QPushButton("SET PRIORITY")
        menu = QMenu(pri)
        for name in actions.PRIORITIES:
            menu.addAction(name, lambda n=name: self._priority(n))
        pri.setMenu(menu)
        row.addWidget(pri)
        row.addStretch(1)
        self.kill_button = QPushButton("KILL PROCESS")
        self.kill_button.setProperty("kind", "primary")
        self.kill_button.clicked.connect(self._kill)
        row.addWidget(self.kill_button)
        close = QPushButton("CLOSE")
        close.clicked.connect(self.close)
        row.addWidget(close)
        b.addLayout(row)
        window.updated.connect(self.tick)
        self.tick()

    def _image(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 8, 0, 0)
        v.setSpacing(10)
        i = self.info
        top = QHBoxLayout()
        top.setSpacing(14)
        icon = QLabel()
        icon.setPixmap(widgets.line_icon("app", theme.LED_ORANGE, 44).pixmap(44, 44))
        top.addWidget(icon)
        t = QVBoxLayout()
        t.setSpacing(0)
        n = QLabel((i.get("description") or i.get("name") or str(self.pid)).upper())
        n.setObjectName("big")
        t.addWidget(n)
        sub = "  ·  ".join(x for x in (i.get("company"), f"version {i['version']}" if i.get("version") else "",
                                       i.get("name"), f"PID {self.pid}") if x)
        s = QLabel(sub)
        s.setObjectName("note")
        t.addWidget(s)
        top.addLayout(t, 1)
        v.addLayout(top)
        g = QGridLayout()
        g.setHorizontalSpacing(16)
        g.setVerticalSpacing(8)
        started = i.get("started")
        when = ""
        if started:
            run = int(time.time() - started)
            when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)) + \
                f"  ·  running {run // 3600} h {run % 3600 // 60} min"
        counts = "  ·  ".join(x for x in (i.get("priority") or "",
                                          f"{i['handles']:,} handles" if i.get("handles") is not None else "",
                                          f"{i['threads']:,} threads" if i.get("threads") is not None else "") if x)
        self.fields = {}
        for r, (k, val) in enumerate((("PATH", i.get("exe")), ("COMMAND LINE", i.get("cmdline")),
                                      ("CURRENT FOLDER", i.get("cwd")),
                                      ("PARENT", f"{i['parent']} ({i['ppid']})" if i.get("parent") else
                                       (f"Ended ({i['ppid']})" if i.get("ppid") else "")),
                                      ("USER", i.get("user")), ("STARTED", when), ("PRIORITY", counts))):
            g.addWidget(keyed(k), r, 0, Qt.AlignmentFlag.AlignTop)
            lab = QLabel(val or "Not available (run as administrator)" if val is None else val)
            lab.setObjectName("value")
            lab.setWordWrap(True)
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.fields[k] = lab
            g.addWidget(lab, r, 1)
        g.setColumnStretch(1, 1)
        v.addLayout(g)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.graphs = {k: Graph(label) for k, label in (("cpu", "CPU"), ("private", "PRIVATE BYTES"), ("io", "I/O"))}
        for gr in self.graphs.values():
            gr.setMinimumHeight(110)
            row.addWidget(gr)
        v.addLayout(row)
        v.addStretch(1)
        return page

    def _table(self, headers, rows) -> QTableView:
        model = PaneModel()
        model.set_rows([actions.Row(*(list(r) + [""] * (4 - len(r)))[:4]) for r in rows], headers + [""] * (4 - len(headers)))
        t = QTableView()
        t.setModel(model)
        t.verticalHeader().hide()
        t.setShowGrid(False)
        t.setAlternatingRowColors(True)
        t.verticalHeader().setDefaultSectionSize(24)
        t.horizontalHeader().setStretchLastSection(True)
        for c in range(len(headers), 4):
            t.hideColumn(c)
        t.setColumnWidth(0, 200)
        t.setColumnWidth(1, 220)
        t._model = model                            # kept alive with the view
        return t

    def tick(self):
        h = self.window.sampler.proc_history.get(self.pid)
        snap = self.window.sampler.snapshot
        p = snap.procs.get(self.pid) if snap else None
        if h is None or p is None or p.gone:
            self.kill_button.setEnabled(False)
            self.suspend_button.setEnabled(False)
            self.graphs["cpu"].value = "ENDED"
            self.graphs["cpu"].update()
            return
        self.suspend_button.setText("RESUME" if p.kind == "suspended" else "SUSPEND")
        self.graphs["cpu"].set_data(h["cpu"], f"{p.cpu or 0:.1f}%")
        top = max(list(h["private"]) + [1]) * 1.15
        self.graphs["private"].set_data(h["private"], procs.human(p.private), top=top)
        self.graphs["io"].set_data(h["io"], procs.rate(p.io), top=None)

    def _kill(self):
        if option("confirm_kill") and not self.window._ask("confirm", f"End {self.info.get('name')} ({self.pid})?"):
            return
        self.window._act(actions.kill, self.pid)

    def _suspend(self):
        p = self.window.sampler.snapshot.procs.get(self.pid)
        self.window._act(actions.resume if p is not None and p.kind == "suspended" else actions.suspend, self.pid)

    def _priority(self, name):
        self.window._act(actions.set_priority, self.pid, name)
        self.fields["PRIORITY"].setText(actions.priority(self.pid))

    def closeEvent(self, e):
        if not getattr(self, "_unhooked", False):      # closed by the user, then again with the window: once
            self._unhooked = True
            try:
                self.window.updated.disconnect(self.tick)
            except (RuntimeError, TypeError):
                pass
        super().closeEvent(e)


# ======================================================================== System Information
class SystemInfoDialog(QDialog):
    """Process Explorer's System Information: Summary, CPU (each core), Memory, I/O, live."""

    def __init__(self, window: MainWindow):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("System Information - Paragon PR7-SM")
        self.resize(1100, 720)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.header = widgets.Header("SYSTEM INFORMATION")
        v.addWidget(self.header)
        b = QVBoxLayout()
        b.setContentsMargins(24, 16, 24, 20)
        b.setSpacing(12)
        v.addLayout(b, 1)
        self.tabs = QTabBar()
        for t in ("SUMMARY", "CPU", "MEMORY", "I/O"):
            self.tabs.addTab(t)
        self.tabs.setExpanding(False)
        b.addWidget(self.tabs)
        self.pages = QStackedWidget()
        b.addWidget(self.pages, 1)
        self.rows = {}
        self.pages.addWidget(self._rows([("cpu", "CPU USAGE"), ("commit", "COMMIT CHARGE"),
                                         ("physical", "PHYSICAL MEMORY"), ("io", "I/O BYTES")]))
        cores = QWidget()
        cg = QGridLayout(cores)
        cg.setSpacing(8)
        self.cores = []
        n = len(window.sampler.core_history) or (os.cpu_count() or 1)
        cols = 4 if n > 4 else n
        for i in range(n):
            g = Graph(f"CPU {i}", small=True)
            g.setMinimumHeight(70)
            self.cores.append(g)
            cg.addWidget(g, i // cols, i % cols)
        self.pages.addWidget(cores)
        self.pages.addWidget(self._rows([("commit2", "COMMIT CHARGE"), ("physical2", "PHYSICAL MEMORY")]))
        self.pages.addWidget(self._rows([("read", "READS"), ("write", "WRITES")]))
        self.tabs.currentChanged.connect(self.pages.setCurrentIndex)
        window.updated.connect(self.tick)
        self.tick()

    def _rows(self, rows) -> QWidget:
        page = QWidget()
        g = QGridLayout(page)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(18)
        g.setVerticalSpacing(8)
        for i, (key, label) in enumerate(rows):
            col = QVBoxLayout()
            col.setSpacing(2)
            col.addWidget(keyed(label))
            big = QLabel("")
            big.setObjectName("big")
            col.addWidget(big)
            note = QLabel("")
            note.setObjectName("note")
            note.setWordWrap(True)
            col.addWidget(note)
            col.addStretch(1)
            box = QWidget()
            box.setLayout(col)
            box.setFixedWidth(280)
            g.addWidget(box, i, 0)
            graph = Graph()
            graph.setMinimumHeight(110)
            g.addWidget(graph, i, 1)
            self.rows[key] = (big, note, graph)
        g.setColumnStretch(1, 1)
        return page

    def _set(self, key, big, note, values, second=None, top=100.0):
        b, n, g = self.rows[key]
        b.setText(big)
        n.setText(note)
        g.set_data(values, "", second, top)

    def tick(self):
        s = self.window.sampler
        snap = s.snapshot
        if snap is None:
            return
        t, h = snap.totals, s.history
        cpu_note = f"{t.cores} cores  ·  {t.threads} threads" + (f"  ·  {t.ghz:.1f} GHz" if t.ghz else "") + \
            "\nKernel time in pearl"
        self._set("cpu", f"{t.cpu:.1f}%", cpu_note, h["cpu"], h["kernel"])
        commit = (f"{procs.human(t.commit)}", f"Limit {procs.human(t.commit_limit)}  ·  peak {procs.human(t.commit_peak)}")
        physical = (procs.human(t.physical), f"Total {procs.human(t.physical_total)}  ·  available "
                                             f"{procs.human(t.available)}")
        for k in ("commit", "commit2"):
            self._set(k, *commit, h["commit"])
        for k in ("physical", "physical2"):
            self._set(k, *physical, h["physical"])
        both = [r + w for r, w in zip(h["read"], h["write"])]
        self._set("io", procs.rate(t.read + t.write), f"Reads {procs.rate(t.read)}  ·  writes {procs.rate(t.write)}\n"
                                                      "Writes in pearl", both, h["write"], top=None)
        self._set("read", procs.rate(t.read), "", h["read"], top=None)
        self._set("write", procs.rate(t.write), "", h["write"], top=None)
        for g, d in zip(self.cores, s.core_history):
            g.set_data(d, f"{d[-1]:.0f}%" if d else "")

    def closeEvent(self, e):
        if not getattr(self, "_unhooked", False):      # closed by the user, then again with the window: once
            self._unhooked = True
            try:
                self.window.updated.disconnect(self.tick)
            except (RuntimeError, TypeError):
                pass
        super().closeEvent(e)


# ======================================================================== Find Handle or DLL
class FindDialog(QDialog):
    def __init__(self, window: MainWindow):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("Find a handle or DLL - Paragon PR7-SM")
        self.resize(820, 520)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(10)
        v.addWidget(keyed("FIND A HANDLE OR DLL"))
        row = QHBoxLayout()
        self.text = QLineEdit()
        self.text.setPlaceholderText("Part of a file or DLL name, e.g. kernel32.dll or a folder")
        self.text.returnPressed.connect(self.search)
        row.addWidget(self.text, 1)
        go = QPushButton("SEARCH")
        go.setProperty("kind", "primary")
        go.clicked.connect(self.search)
        row.addWidget(go)
        v.addLayout(row)
        self.model = PaneModel()
        self.model.headers = ["PROCESS", "PID", "TYPE", "NAME"]
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(self._go)
        v.addWidget(self.table, 1)
        self.note = QLabel("Double-click a result to select its process.")
        self.note.setObjectName("note")
        v.addWidget(self.note)
        self.results: list[actions.Found] = []
        window.bridge.found.connect(self._found)

    def search(self):
        text = self.text.text()
        self.note.setText("Searching every process...")
        if self.window.sync:
            self._found(actions.find(text))
        else:
            threading.Thread(target=lambda: self.window.bridge.found.emit(actions.find(text)), daemon=True).start()

    def _found(self, results):
        self.results = results
        self.model.set_rows([actions.Row(f.process, str(f.pid), f.kind, f.path) for f in results])
        self.note.setText(f"{len(results):,} found. Double-click one to select its process.")

    def _go(self, index):
        f = self.results[index.row()]
        self.window.filter.clear()
        self.window.select(f.pid)


# ======================================================================== Options
class OptionsDialog(QDialog):
    def __init__(self, window: MainWindow):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("Paragon PR7-SM")
        self.resize(600, 520)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.header = widgets.Header("SYSTEM")
        v.addWidget(self.header)
        b = QVBoxLayout()
        b.setContentsMargins(26, 18, 26, 22)
        b.setSpacing(12)
        v.addLayout(b, 1)
        b.addWidget(keyed("UPDATES"))
        row = QHBoxLayout()
        row.addWidget(QLabel("Refresh every"))
        self.refresh = QComboBox()
        for ms, text in ((500, "half a second"), (1000, "second"), (2000, "2 seconds"), (5000, "5 seconds"),
                         (10000, "10 seconds")):
            self.refresh.addItem(text, ms)
        self.refresh.setCurrentIndex(max(0, self.refresh.findData(option("refresh_ms"))))
        row.addWidget(self.refresh)
        row.addSpacing(20)
        row.addWidget(QLabel("Show new and ending processes for"))
        self.highlight = QComboBox()
        for s in (1, 2, 3, 5, 10):
            self.highlight.addItem(f"{s} s", s)
        self.highlight.setCurrentIndex(max(0, self.highlight.findData(option("highlight_s"))))
        row.addWidget(self.highlight)
        row.addStretch(1)
        b.addLayout(row)
        self.confirm = QCheckBox("Ask before ending a process")
        self.confirm.setChecked(option("confirm_kill"))
        b.addWidget(self.confirm)
        b.addWidget(keyed("TASK MANAGER"))
        self.tm_state = QLabel("")
        self.tm_state.setObjectName("note")
        self.tm_state.setWordWrap(True)
        b.addWidget(self.tm_state)
        row = QHBoxLayout()
        self.tm_button = QPushButton("")
        self.tm_button.clicked.connect(self.toggle_taskmgr)
        self.tm_button.setEnabled(taskmgr.available())
        row.addWidget(self.tm_button)
        row.addStretch(1)
        b.addLayout(row)
        self._tm_text()
        b.addWidget(keyed("STARTING"))
        from . import update_ui
        self.updates = QCheckBox("Check for updates automatically")
        self.updates.setChecked(update_ui.auto_enabled())
        b.addWidget(self.updates)
        b.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        ok = QPushButton("OK")
        ok.setProperty("kind", "primary")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("CANCEL")
        cancel.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        b.addLayout(row)

    def _tm_text(self):
        on = taskmgr.is_replaced()
        self.tm_state.setText("Ctrl+Shift+Esc and every Task Manager link open PR7-SM." if on else
                              "Replace Task Manager: Ctrl+Shift+Esc and every Task Manager link open PR7-SM instead. "
                              "Windows asks for permission once.")
        self.tm_button.setText("PUT TASK MANAGER BACK" if on else "REPLACE TASK MANAGER")

    def toggle_taskmgr(self):
        arg = "--restore-taskmgr" if taskmgr.is_replaced() else "--replace-taskmgr"
        run = self.window.answers.get("elevated", taskmgr.run_elevated)
        code = run(arg)
        if code == -1:
            self.window._say("info", "Windows' permission prompt was declined: nothing was changed.")
        elif code != 0:
            self.window._say("warning", f"That didn't work (code {code}).")
        self._tm_text()

    def save(self):
        settings.set("refresh_ms", self.refresh.currentData())
        settings.set("highlight_s", self.highlight.currentData())
        settings.set("confirm_kill", self.confirm.isChecked())
        from . import update_ui
        update_ui.set_auto(self.updates.isChecked())
