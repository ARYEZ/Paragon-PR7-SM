"""Mock-up pictures of PR7-SM, drawn offscreen with real Qt widgets: QT_SCALE_FACTOR=2 python tools/mockup.py OUT
Every number here is made up."""
import math
import os
import random
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, QRectF, QSize, Qt  # noqa: E402
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen  # noqa: E402
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFrame, QGridLayout, QHBoxLayout, QHeaderView,  # noqa
                               QLabel, QLineEdit, QPushButton, QTabBar, QTableWidget, QTableWidgetItem, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from pr7sm import theme, widgets  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/mockup")
out.mkdir(parents=True, exist_ok=True)
app = QApplication([])
theme.load_fonts()
rnd = random.Random(11)

# Process Explorer's row colours in the family's: services pink, your own processes orange, new pearl, ending red,
# suspended onyx. Drawn as a soft tint behind the row, the text stays readable.
KIND = {"service": "#E0457B", "own": "#F07A2A", "new": "#E8E2E6", "ending": "#F4353A", "suspended": "#55505A"}

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


class Graph(QWidget):
    """A history graph: the family gradient as the line, a faint fill under it, grid lines; an optional second line
    (kernel time, or writes) in pearl."""

    def __init__(self, values, second=None, label="", value="", small=False):
        super().__init__()
        self.values, self.second, self.label, self.value, self.small = values, second, label, value, small
        self.setMinimumSize(QSize(110 if small else 200, 30 if small else 120))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        p.setPen(QPen(QColor(theme.PANEL_EDGE), 1))
        p.setBrush(QColor(theme.WIDGET))
        p.drawRoundedRect(r, 3, 3)
        if not self.small:
            p.setPen(QPen(QColor(theme.PANEL_EDGE), 1, Qt.PenStyle.DotLine))
            for k in range(1, 4):
                y = r.top() + r.height() * k / 4
                p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        inner = r.adjusted(2, 15, -2, -2) if self.small else r.adjusted(2, 3, -2, -2)

        def path(vals):
            pa = QPainterPath()
            for i, v in enumerate(vals):
                pt = QPointF(inner.left() + inner.width() * i / (len(vals) - 1), inner.bottom() - inner.height() * v / 100)
                pa.moveTo(pt) if i == 0 else pa.lineTo(pt)
            return pa
        line = path(self.values)
        fill = QPainterPath(line)                     # the area under the line: closed along the bottom, winding fill
        fill.lineTo(inner.bottomRight())
        fill.lineTo(inner.bottomLeft())
        fill.closeSubpath()
        fill.setFillRule(Qt.FillRule.WindingFill)
        g = QLinearGradient(inner.topLeft(), inner.bottomLeft())
        c1 = QColor(theme.ACCENT); c1.setAlphaF(.35)
        c2 = QColor(theme.ACCENT); c2.setAlphaF(.02)
        g.setColorAt(0, c1); g.setColorAt(1, c2)
        p.fillPath(fill, QBrush(g))
        p.setBrush(Qt.BrushStyle.NoBrush)             # drawPath would otherwise fill the line's chord with the old brush
        p.setPen(QPen(QBrush(theme.family_gradient(inner.left(), 0, inner.right(), 0)), 1.6 if self.small else 2))
        p.drawPath(line)
        if self.second:
            pen = QPen(QColor(theme.TEXT), 1.2)
            pen.setColor(QColor(theme.TEXT_DIM))
            p.setPen(pen)
            p.drawPath(path(self.second))
        if self.label:
            f = QFont("Inter"); f.setPixelSize(10 if self.small else 11); f.setWeight(QFont.Weight.DemiBold)
            p.setFont(f)
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(r.adjusted(6, 3, -6, -3), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, self.label)
            p.setPen(QColor(theme.TEXT))
            p.drawText(r.adjusted(6, 3, -6, -3), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop, self.value)


def base(w, finish, extra=""):
    theme.set_finish(finish)
    app.setPalette(theme.palette())
    w.setPalette(theme.palette()); w.setAutoFillBackground(True)
    extra = extra() if callable(extra) else extra
    w.setStyleSheet(theme.stylesheet() + f"""
QTreeWidget::item:selected, QTableWidget::item:selected {{ background: {theme.ACCENT_DIM}; color: #FFFFFF; }}
QTableWidget {{ alternate-background-color: {theme.ALT_ROW}; }}
QLabel#key {{ color: {theme.TEXT_DIM}; font-size: 11px; font-weight: 600; letter-spacing: 1px; }}
QLabel#big {{ font-size: 22px; font-weight: 600; }}
QLabel#note {{ color: {theme.TEXT_DIM}; }}
QPushButton[kind="primary"] {{ background: {theme.qss_gradient()}; color: #FFFFFF; border: none; border-radius: 4px;
    padding: 9px 22px; font-weight: 600; }}
QFrame#pane {{ background: {theme.PANEL}; border-top: 1px solid {theme.PANEL_EDGE}; }}
""" + extra)


def keyed(t):
    lab = QLabel(t); lab.setObjectName("key"); return lab


def mb(v):
    if v == "" or v is None:
        return ""
    return f"{v * 1024:,.0f} K" if v < 1 else (f"{v:,.1f} MB" if v < 1024 else f"{v / 1024:,.2f} GB")


from PySide6.QtWidgets import QStyledItemDelegate  # noqa: E402

TINT_ROLE = Qt.ItemDataRole.UserRole + 1


class TintDelegate(QStyledItemDelegate):
    """Process Explorer's row colours: the tint first, then the normal row (text, hover, selection) on top. The
    theme's ::item rules make Qt ignore an item's own background, so the delegate paints it."""

    def paint(self, p, option, index):
        c = index.data(TINT_ROLE)
        if c is not None:
            p.fillRect(option.rect, c)
        super().paint(p, option, index)


def tint(kind):
    c = QColor(KIND[kind]); c.setAlphaF(.22 if kind != "suspended" else .5); return c


# ---------------------------------------------------------------- 1. the process tree
def main():
    w = QWidget(); w.resize(1280, 960)
    base(w, "obsidian")
    v = QVBoxLayout(w); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)
    v.addWidget(widgets.Header("SYSTEM"))
    bar = QHBoxLayout(); bar.setContentsMargins(14, 10, 14, 10); bar.setSpacing(4)
    for icon, tip in (("refresh", "Refresh now (F5)"), ("pause", "Pause updates (Space)"), (None, None),
                      ("info", "Properties (Enter)"), ("close", "Kill process (Del)"), ("search", "Find a handle or DLL (Ctrl+F)"),
                      (None, None), ("chart", "System information (Ctrl+I)")):
        if icon is None:
            bar.addSpacing(14)
        else:
            bar.addWidget(widgets.SmallKey(icon, tip))
    bar.addSpacing(18)
    for label, val, base_, wob, sec in (("CPU", "12.4%", 14, 6, True), ("MEMORY", "47%", 47, .8, False),
                                        ("I/O", "38 MB/s", 25, 14, True)):
        g = Graph(series(60, base_, wob, len(label)), series(60, base_ / 3, wob / 2, len(label) + 9) if sec else None,
                  label, val, small=True)
        g.setFixedSize(150, 40)
        bar.addWidget(g)
    bar.addStretch(1)
    s = QLineEdit(); s.setPlaceholderText("Filter by name"); s.setFixedWidth(260); bar.addWidget(s)
    bar.addWidget(widgets.SmallKey("more", "Menu"))
    v.addLayout(bar)
    tree = QTreeWidget()
    tree.setColumnCount(7)
    tree.setHeaderLabels(["PROCESS", "CPU", "PRIVATE BYTES", "WORKING SET", "PID", "DESCRIPTION", "COMPANY NAME"])
    tree.setRootIsDecorated(True); tree.setIndentation(16); tree.setFrameShape(QFrame.Shape.NoFrame)
    tree.setIconSize(QSize(16, 16)); tree.setUniformRowHeights(True)
    tree.setItemDelegate(TintDelegate(tree))
    stack = []
    sel = None
    for depth, name, cpu, priv, ws, pid, desc, comp, kind in PROCS:
        it = QTreeWidgetItem([name, f"{cpu:.2f}" if cpu != "" else "", mb(priv), mb(ws), str(pid), desc, comp])
        it.setIcon(0, widgets.line_icon("app" if name.endswith(".exe") else "chart", theme.TEXT_DIM, 16))
        for c in (1, 2, 3, 4):
            it.setTextAlignment(c, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if kind:
            for c in range(7):
                it.setData(c, TINT_ROLE, tint(kind))
        if kind == "ending":
            for c in range(7):
                it.setForeground(c, QColor("#FFB4B6"))
        stack = stack[:depth]
        if depth == 0:
            tree.addTopLevelItem(it)
        else:
            stack[-1].addChild(it)
        stack.append(it)
        if name == "Resolve.exe":
            sel = it
    tree.expandAll()
    h = tree.header()
    for c, cw in ((0, 250), (1, 64), (2, 120), (3, 120), (4, 70), (5, 290)):
        h.resizeSection(c, cw)
    h.setStretchLastSection(True)
    for c in (1, 2, 3, 4):
        tree.headerItem().setTextAlignment(c, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    tree.setCurrentItem(sel)
    tree.scrollToTop()
    v.addWidget(tree, 1)
    pane = QFrame(); pane.setObjectName("pane")
    pv = QVBoxLayout(pane); pv.setContentsMargins(0, 6, 0, 0); pv.setSpacing(0)
    tabs = QTabBar(); tabs.addTab("DLLS"); tabs.addTab("HANDLES"); tabs.setExpanding(False)
    row = QHBoxLayout(); row.setContentsMargins(14, 0, 14, 4); row.addWidget(tabs); row.addStretch(1)
    t = QLabel("Resolve.exe  ·  PID 9032  ·  412 DLLs"); t.setObjectName("note"); row.addWidget(t)
    pv.addLayout(row)
    dl = QTableWidget(len(DLLS), 4); dl.setHorizontalHeaderLabels(["NAME", "DESCRIPTION", "COMPANY NAME", "PATH"])
    dl.verticalHeader().hide(); dl.setShowGrid(False); dl.setAlternatingRowColors(True); dl.setFrameShape(QFrame.Shape.NoFrame)
    dl.verticalHeader().setDefaultSectionSize(25)
    DL = DLLS[:5]
    dl.setRowCount(len(DL))
    for r, vals in enumerate(DL):
        for c, val in enumerate(vals):
            dl.setItem(r, c, QTableWidgetItem(val))
    for c, cw in ((0, 180), (1, 300), (2, 200)):
        dl.setColumnWidth(c, cw)
    dl.horizontalHeader().setStretchLastSection(True)
    dl.setFixedHeight(25 * 5 + 32)
    pv.addWidget(dl)
    v.addWidget(pane)
    st = QHBoxLayout(); st.setContentsMargins(14, 7, 14, 7)
    for text in ("CPU 12.4%", "Commit 9.21 GB of 31.8 GB (29%)", "Physical memory 47%", "Processes 214"):
        lab = QLabel(text); lab.setObjectName("note"); st.addWidget(lab); st.addSpacing(18)
    st.addStretch(1)
    leg = QHBoxLayout(); leg.setSpacing(6)
    for kind, label in (("service", "SERVICES"), ("own", "YOUR PROCESSES"), ("new", "NEW"), ("ending", "ENDING"),
                        ("suspended", "SUSPENDED")):
        sw = QLabel(); sw.setFixedSize(10, 10)
        sw.setStyleSheet(f"background: {KIND[kind]}; border-radius: 2px;")
        leg.addWidget(sw)
        leg.addWidget(keyed(label)); leg.addSpacing(8)
    st.addLayout(leg)
    v.addLayout(st)
    return w


# ---------------------------------------------------------------- 2. system information (AURORA)
def sysinfo():
    w = QWidget(); w.resize(1100, 720)
    base(w, "aurora")
    v = QVBoxLayout(w); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)
    v.addWidget(widgets.Header("SYSTEM INFORMATION"))
    b = QVBoxLayout(); b.setContentsMargins(24, 16, 24, 20); b.setSpacing(12); v.addLayout(b, 1)
    tabs = QTabBar()
    for t in ("SUMMARY", "CPU", "MEMORY", "I/O", "GPU"):
        tabs.addTab(t)
    tabs.setExpanding(False); b.addWidget(tabs)
    g = QGridLayout(); g.setHorizontalSpacing(18); g.setVerticalSpacing(8)
    rows = (("CPU USAGE", "12.4%", series(120, 14, 6, 3), series(120, 5, 3, 4), "16 cores · 32 threads · 4.2 GHz",
             "Kernel time in pearl"),
            ("COMMIT CHARGE", "9.21 GB", series(120, 29, .6, 5), None, "Limit 31.8 GB  ·  peak 12.6 GB", ""),
            ("PHYSICAL MEMORY", "15.0 GB", series(120, 47, .5, 6), None, "Total 31.9 GB  ·  available 16.9 GB", ""),
            ("I/O BYTES", "38.2 MB/s", series(120, 25, 14, 7), series(120, 9, 6, 8), "Reads 31.4 MB/s  ·  writes 6.8 MB/s",
             "Writes in pearl"))
    for i, (label, val, s1, s2, note, legend) in enumerate(rows):
        col = QVBoxLayout(); col.setSpacing(2)
        col.addWidget(keyed(label))
        big = QLabel(val); big.setObjectName("big"); col.addWidget(big)
        n = QLabel(note); n.setObjectName("note"); n.setWordWrap(True); col.addWidget(n)
        if legend:
            l2 = QLabel(legend); l2.setObjectName("note"); col.addWidget(l2)
        col.addStretch(1)
        box = QWidget(); box.setLayout(col); box.setFixedWidth(280)
        g.addWidget(box, i, 0)
        graph = Graph(s1, s2)
        graph.setMinimumHeight(118)
        g.addWidget(graph, i, 1)
    g.setColumnStretch(1, 1)
    b.addLayout(g, 1)
    return w


# ---------------------------------------------------------------- 3. process properties
def props():
    w = QWidget(); w.resize(760, 600)
    base(w, "obsidian", "QLabel#value { font-size: 13px; }")
    v = QVBoxLayout(w); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)
    v.addWidget(widgets.Header("PROPERTIES"))
    b = QVBoxLayout(); b.setContentsMargins(24, 16, 24, 20); b.setSpacing(10); v.addLayout(b, 1)
    tabs = QTabBar()
    for t in ("IMAGE", "PERFORMANCE", "THREADS", "TCP/IP", "ENVIRONMENT"):
        tabs.addTab(t)
    tabs.setExpanding(False); b.addWidget(tabs)
    top = QHBoxLayout(); top.setSpacing(14)
    icon = QLabel(); icon.setPixmap(widgets.line_icon("app", theme.LED_ORANGE, 44).pixmap(44, 44)); top.addWidget(icon)
    t = QVBoxLayout(); t.setSpacing(0)
    n = QLabel("DAVINCI RESOLVE"); n.setObjectName("big"); t.addWidget(n)
    s = QLabel("Blackmagic Design  ·  version 20.1.0.0045  ·  Resolve.exe  ·  PID 9032"); s.setObjectName("note")
    t.addWidget(s); top.addLayout(t, 1)
    b.addLayout(top)
    g = QGridLayout(); g.setHorizontalSpacing(16); g.setVerticalSpacing(8)
    for r, (k, val) in enumerate((("PATH", r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe"),
                                  ("COMMAND LINE", r'"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe" '
                                                   r'"D:\Projects\Elseworld\Elseworld edit.drp"'),
                                  ("CURRENT FOLDER", "D:\\Projects\\Elseworld\\"),
                                  ("PARENT", "explorer.exe (6216)"), ("USER", r"STUDIO\me"),
                                  ("STARTED", "2026-11-25 09:14:02  ·  running 2 h 41 min"),
                                  ("PRIORITY", "Normal  ·  64-bit  ·  412 DLLs  ·  2,184 handles  ·  96 threads"))):
        g.addWidget(keyed(k), r, 0, Qt.AlignmentFlag.AlignTop)
        lab = QLabel(val); lab.setObjectName("value"); lab.setWordWrap(True)
        g.addWidget(lab, r, 1)
    g.setColumnStretch(1, 1)
    b.addLayout(g)
    b.addSpacing(6)
    row = QHBoxLayout(); row.setSpacing(12)
    for label, val, s1 in (("CPU", "6.4%", series(80, 12, 7, 21)), ("PRIVATE BYTES", "4.02 GB", series(80, 60, 1.5, 22)),
                           ("I/O", "22 MB/s", series(80, 20, 12, 23))):
        gr = Graph(s1, None, label, val); gr.setMinimumHeight(110); row.addWidget(gr)
    b.addLayout(row)
    b.addStretch(1)
    row = QHBoxLayout()
    for label in ("OPEN FOLDER", "SUSPEND", "SET PRIORITY"):
        row.addWidget(QPushButton(label))
    row.addStretch(1)
    k = QPushButton("KILL PROCESS"); k.setProperty("kind", "primary"); row.addWidget(k)
    row.addWidget(QPushButton("CLOSE"))
    b.addLayout(row)
    return w


for name, make in (("1_processes.png", main), ("2_system_aurora.png", sysinfo), ("3_properties.png", props)):
    win = make()
    win.show(); app.processEvents()
    for t in win.findChildren(QTreeWidget):           # after the layout: the tree from its first row
        t.scrollToTop()
    app.processEvents()
    win.grab().save(str(out / name))
    print(out / name)
