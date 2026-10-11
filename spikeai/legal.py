import glob
import hashlib
import html
import os
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QDialog, QHBoxLayout, QListWidget, QTextBrowser, QVBoxLayout, QLabel
from .resources import resource_path

DISCLAIMER_TITLE = "Riot Games Disclaimer"
DISCLAIMER = (
    "Spike AI is an independent third-party application and is not affiliated with, associated with, "
    "authorized by, endorsed by, or sponsored by Riot Games, Inc.",
    "VALORANT, Riot Games, and all related trademarks, characters, artwork, and assets are the property "
    "of Riot Games, Inc. and their respective owners.",
    "Spike AI is developed independently by Kira Kohler.",
)

DOCUMENTS = (
    ("Spike AI notice", ("licenses/NOTICE.txt",)),
    ("Agent artwork", ("ATTRIBUTIONS.md",)),
    (
        "Open-source licenses",
        (
            "licenses/Qt-notice.md",
            "licenses/LGPL-3.0-only.txt",
            "licenses/GPL-3.0-only.txt",
            "licenses/PySide6*",
            "licenses/shiboken6*",
            "licenses/opencv-python-*",
            "licenses/numpy-*",
            "licenses/mss-*",
            "licenses/Python-*",
            "licenses/pywinrt-*",
            "licenses/pyinstaller-*",
            "licenses/Kokoro-*",
            "licenses/kokoro-*",
        ),
    ),
)


def document_files(patterns):
    files, seen = [], set()
    for pattern in patterns:
        for path in sorted(glob.glob(resource_path(*pattern.split("/")))):
            if not os.path.isfile(path):
                continue
            with open(path, "rb") as f:
                digest = hashlib.sha256(f.read()).digest()
            if digest not in seen:
                seen.add(digest)
                files.append(path)
    return files


def document_html(patterns):
    parts = []
    for path in document_files(patterns):
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        if path.lower().endswith(".md"):
            doc = QTextDocument()
            doc.setMarkdown(text)
            body = doc.toHtml()
            body = body[body.find("<body") :]
            body = body[body.find(">") + 1 : body.rfind("</body>")]
            parts.append(body.replace("color:#0000ff;", "color:#ff8a94;").replace("text-decoration: underline;", ""))
        else:
            parts.append('<p style="white-space:pre-wrap;">' + html.escape(text) + "</p>")
    return '<hr style="margin:18px 0;"/>'.join(parts)


class LegalDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Licenses & Legal")
        self.setObjectName("page")
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)
        self.setModal(True)
        self.resize(820, 540)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        title = QLabel("Licenses & Legal")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.list = QListWidget()
        self.list.setFixedWidth(220)
        self.list.setStyleSheet(
            "QListWidget { background:#0d1621; border:1px solid #2c3a4a; border-radius:8px; padding:4px; outline:0; }"
            "QListWidget::item { padding:9px 10px; border-radius:6px; color:#cfd9e3; }"
            "QListWidget::item:selected { background:#25344a; color:#ffffff; }"
        )
        self.text = QTextBrowser()
        self.text.setOpenExternalLinks(True)
        self.text.document().setDefaultStyleSheet(
            "a { color:#ff8a94; text-decoration:none; } th, td { padding:3px 8px; } h1 { font-size:20px; }"
        )
        self.text.setStyleSheet(
            "QTextBrowser { background:#09121c; border:1px solid #304253; border-radius:8px; padding:10px; }"
        )
        for name, _ in DOCUMENTS:
            self.list.addItem(name)
        self.list.currentRowChanged.connect(self.show_document)
        row.addWidget(self.list)
        row.addWidget(self.text, 1)
        layout.addLayout(row, 1)
        self.list.setCurrentRow(0)

    def show_document(self, index):
        if 0 <= index < len(DOCUMENTS):
            self.text.setHtml(document_html(DOCUMENTS[index][1]))
            self.text.verticalScrollBar().setValue(0)
