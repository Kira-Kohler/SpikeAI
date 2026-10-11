from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QMenu, QSystemTrayIcon
from .logsys import log
from .themes import theme

TITLE = "Spike AI is still running"
MESSAGE = "Spike AI has been minimized to the system tray. Right-click its icon to exit."

MENU_STYLE = """
QMenu { background:SURFACE; border:1px solid BORDER; border-radius:8px; padding:6px; }
QMenu::item { color:#e5edf2; padding:9px 30px 9px 16px; border-radius:5px; font:13px 'Segoe UI'; }
QMenu::item:selected { background:HOVER; color:#ffffff; }
QMenu::item:disabled { color:#6f7b88; }
QMenu::separator { height:1px; background:BORDER; margin:5px 8px; }
"""


class Tray(QObject):
    def __init__(self, controller, window):
        super().__init__(window)
        self.controller = controller
        self.window = window
        self.cfg = controller.cfg.data
        self.notified = False
        self.icon = QSystemTrayIcon(window.windowIcon(), window)
        self.menu = QMenu()
        self.menu.setWindowFlags(self.menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.menu.setAttribute(Qt.WA_TranslucentBackground)
        self.open_action = self.menu.addAction("Open Spike AI", window.reveal)
        self.detection_action = self.menu.addAction("Pause detection", controller.toggle_detection)
        self.menu.addSeparator()
        self.exit_action = self.menu.addAction("Exit Spike AI", controller.close)
        self.menu.aboutToShow.connect(self.refresh)
        self.icon.setContextMenu(self.menu)
        self.icon.setToolTip("Spike AI")
        self.icon.activated.connect(self.activated)
        self.refresh()

    def show(self):
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.icon.show()
        return self.icon.isVisible()

    def available(self):
        return QSystemTrayIcon.isSystemTrayAvailable() and self.icon.isVisible()

    def activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.window.reveal()

    def refresh(self):
        spec = theme(self.cfg)
        accent = QColor(self.cfg["accent"])
        self.detection_action.setText(
            "Pause detection" if self.cfg["detection_enabled"] else "Resume detection"
        )
        self.menu.setStyleSheet(
            MENU_STYLE.replace("SURFACE", spec.surface)
            .replace("BORDER", "#33404f")
            .replace("HOVER", f"rgba({accent.red()},{accent.green()},{accent.blue()},90)")
        )

    def notify_hidden(self):
        if self.notified or not self.cfg["tray_notifications"] or not self.available():
            return False
        if not QSystemTrayIcon.supportsMessages():
            return False
        self.notified = True
        self.icon.showMessage(TITLE, MESSAGE, self.icon.icon(), 6000)
        log.info("Tray notification shown")
        return True

    def hide(self):
        self.icon.hide()
        self.menu.close()
