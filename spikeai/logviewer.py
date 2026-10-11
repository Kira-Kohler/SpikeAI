import os
from pathlib import Path
import threading
import queue
from collections import deque
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor, QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QLabel,
    QFileDialog,
    QApplication,
)

from .widgets import AnimatedButton as QPushButton, AnimatedSwitch as QCheckBox
from .controls import StyledCombo


class TailReader:
    def __init__(self, path, limit=32 * 1024):
        self.path = Path(os.path.expandvars(str(path)))
        self.limit = limit
        self.offset = 0
        self.identity = None
        self.pending = b""
        self.anchor = b""
        self.available = False

    def poll(self):
        try:
            with self.path.open("rb") as stream:
                self.available = True
                stat = os.fstat(stream.fileno())
                ident = (stat.st_dev, stat.st_ino)
                reset = ident != self.identity or stat.st_size < self.offset
                if not reset and self.offset and self.anchor:
                    stream.seek(max(0, self.offset - len(self.anchor)))
                    reset = stream.read(len(self.anchor)) != self.anchor
                if reset:
                    self.offset = max(0, stat.st_size - self.limit) if self.identity is None else 0
                    self.pending = b""
                    stream.seek(self.offset)
                    if self.offset:
                        stream.readline()
                        self.offset = stream.tell()
                    self.identity = ident
                stream.seek(self.offset)
                data = stream.read(self.limit)
                self.offset = stream.tell()
                stream.seek(max(0, self.offset - 128))
                self.anchor = stream.read(min(128, self.offset))
            joined = self.pending + data
            lines = joined.split(b"\n")
            self.pending = lines.pop()[-self.limit :]
            return [line.decode("utf-8", errors="replace").rstrip("\r") for line in lines]
        except (OSError, PermissionError):
            self.available = False
            return []


def level(line):
    lower = line.lower()
    if any(word in lower for word in ("fatal", "error")):
        return "Error"
    if "warn" in lower:
        return "Warning"
    if "debug" in lower or "verbose" in lower:
        return "Debug"
    return "Info"


class TailWorker(threading.Thread):
    def __init__(self, path):
        super().__init__(name="log-reader", daemon=True)
        self.reader = TailReader(path)
        self.output = queue.Queue(maxsize=8)
        self.stop_event = threading.Event()

    def run(self):
        while not self.stop_event.is_set():
            if not self.output.full():
                lines = self.reader.poll()
                if lines:
                    self.output.put_nowait(lines)
            self.stop_event.wait(0.3)


class LogViewer(QWidget):
    def __init__(self, config, save):
        super().__init__()
        self.config, self.save = config, save
        self.lines = deque(maxlen=6000)
        self.pending = deque()
        self.worker = None
        self.path = config["log_path"]
        self.session_closed = False
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        title = QLabel("Valorant Console")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search the last 6,000 lines…")
        self.search.textChanged.connect(self.rebuild)
        filters.addWidget(self.search, 1)
        self.filter = StyledCombo()
        self.filter.setMinimumWidth(130)
        self.filter.addItems(["All", "Error", "Warning", "Info", "Debug"])
        self.filter.currentTextChanged.connect(self.rebuild)
        filters.addWidget(self.filter)
        self.pause = QCheckBox("Pause")
        filters.addWidget(self.pause)
        self.scroll = QCheckBox("Autoscroll")
        self.scroll.setChecked(config["log_autoscroll"])
        self.scroll.toggled.connect(lambda v: save("log_autoscroll", v))
        filters.addWidget(self.scroll)
        layout.addLayout(filters)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(6000)
        self.text.setFont(QFont("Cascadia Mono", 10))
        layout.addWidget(self.text, 1)
        bottom = QHBoxLayout()
        self.status = QLabel()
        bottom.addWidget(self.status, 1)
        copy = QPushButton("Copy view")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.text.toPlainText()))
        bottom.addWidget(copy)
        export = QPushButton("Export view")
        export.clicked.connect(self.export)
        bottom.addWidget(export)
        layout.addLayout(bottom)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(100)
        self.connect_file()

    def connect_file(self, path=None):
        if path:
            self.path = path
            self.save("log_path", path)
        if self.worker:
            self.worker.stop_event.set()
        self.worker = TailWorker(self.path)
        self.worker.start()
        self.lines.clear()
        self.pending.clear()
        self.text.clear()
        self.session_closed = False

    def accepts(self, line):
        return self.search.text().casefold() in line.casefold() and (
            self.filter.currentText() == "All" or level(line) == self.filter.currentText()
        )

    def append(self, line):
        cursor = QTextCursor(self.text.document())
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(
            QColor(
                {"Error": "#ff6b79", "Warning": "#ffc38b", "Info": "#b9c8d4", "Debug": "#7b9aaa"}[level(line)]
            )
        )
        cursor.insertText(line + "\n", fmt)

    def rebuild(self, *args):
        pos = self.text.verticalScrollBar().value()
        self.text.clear()
        for line in self.lines:
            if self.accepts(line):
                self.append(line)
        self.text.verticalScrollBar().setValue(
            self.text.verticalScrollBar().maximum() if self.scroll.isChecked() else pos
        )

    def show_status(self):
        if self.pause.isChecked():
            state = "Paused"
        elif self.session_closed:
            state = "VALORANT closed · waiting for the next session"
        else:
            state = "Connected" if self.worker.reader.available else "Waiting for VALORANT"
        self.status.setText(state + f" · {len(self.lines):,} lines in memory")

    def poll(self):
        if not self.pause.isChecked():
            self.read_pending()
        self.show_status()

    def read_pending(self):
        pos = self.text.verticalScrollBar().value()
        for _ in range(120):
            if not self.pending:
                try:
                    self.pending.extend(self.worker.output.get_nowait())
                except queue.Empty:
                    break
            if not self.pending:
                break
            line = self.pending.popleft()
            if "Log file closed" in line:
                self.session_closed = True
                self.lines.clear()
                self.text.clear()
                continue
            if self.session_closed and not line.strip():
                continue
            self.session_closed = False
            self.lines.append(line)
            if self.accepts(line):
                self.append(line)
        self.text.verticalScrollBar().setValue(
            self.text.verticalScrollBar().maximum() if self.scroll.isChecked() else pos
        )

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export view", "VALORANT-logs.txt", "Text (*.txt)")
        if path:
            try:
                Path(path).write_text(self.text.toPlainText(), encoding="utf-8")
            except OSError as error:
                self.status.setText(str(error))

    def shutdown(self):
        self.timer.stop()
        self.worker.stop_event.set()
        self.worker.join(1)
