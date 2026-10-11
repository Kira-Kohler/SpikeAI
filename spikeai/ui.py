from pathlib import Path
from PySide6.QtCore import (
    Qt,
    QRectF,
    QVariantAnimation,
    QTimer,
    QPoint,
    QPropertyAnimation,
    QParallelAnimationGroup,
    QEasingCurve,
)
from PySide6.QtGui import QColor, QPainter, QFont, QPen, QIcon, QLinearGradient
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QStackedWidget,
    QScrollArea,
    QAbstractScrollArea,
    QSlider,
    QFileDialog,
    QColorDialog,
    QMessageBox,
    QGraphicsOpacityEffect,
    QGridLayout,
)
from . import __version__
from .legal import DISCLAIMER, DISCLAIMER_TITLE, LegalDialog
from .resources import resource_path
from .tray import Tray
from .voice import MARKS, read_voice
from .logviewer import LogViewer
from .themes import THEMES, theme
from .widgets import AnimatedButton, AnimatedSwitch, GlowCard, WheelGuard, ActivityDot, AnimatedScrollBar
from .controls import (
    BrandMark,
    ShimmerText,
    StyledCombo,
    HotkeyField,
    HotkeyCapture,
    KeycapDisplay,
    NavButton,
)
from .art import Hero, ScaledArt, paint_motif
import time

STYLE = """
* { font-family: 'Segoe UI'; font-size: 13px; color: #e5edf2; }
QMainWindow, QWidget#page { background: BG; }
QWidget#sidebar { background:#0b1119; border-right:1px solid #23303e; }
QLabel { background:transparent; }
QLabel#brand { font: 700 26px 'Bahnschrift'; letter-spacing: 2px; }
QLabel#pageTitle { font: 600 29px 'Bahnschrift'; }
QLabel#muted { color:#92a5b7; }
QLabel#eyebrow { color:ACCENT; font:600 11px 'Bahnschrift'; letter-spacing:2px; }
QLabel#legalTitle { font:600 14px 'Bahnschrift'; color:#e5edf2; }
QLabel#legalText { color:#b3c1cf; line-height:140%; }
QLabel#credit { color:#7d8d9e; font-size:12px; }
QFrame#card { background:#141e2a; border:1px solid #283544; border-radius:8px; }
QLabel#cardValue { font:600 20px 'Bahnschrift'; }
QPushButton { background:#1c2938; border:1px solid #344454; padding:10px 15px; border-radius:4px; font-weight:600; }
QPushButton:hover { background:#2a3b4e; border-color:ACCENT; }
QPushButton:pressed { background:#354859; }
QPushButton:focus { border:1px solid #e7e4da; }
QPushButton#primary { background:ACCENT; color:#0b1119; border:1px solid ACCENT; }
QPushButton#primary:hover { background:#ff7681; }
QPushButton#nav { text-align:left; background:transparent; border:0; padding:14px 12px 14px 47px; color:#a0b0c0; border-radius:6px; }
QPushButton#nav:checked { background:#212633; color:#f4f2ee; border-left:3px solid ACCENT; border-radius:0; padding-left:44px; }
QPushButton#nav:hover { background:#192332; color:#ffffff; }
QLineEdit,QSpinBox { background:#0d1621; border:1px solid #354555; border-radius:4px; padding:8px; min-height:20px; }
QLineEdit:focus,QSpinBox:focus { border-color:ACCENT; }
QColorDialog { background:BG; }
QColorDialog QSpinBox { padding:3px 8px; min-width:52px; min-height:22px; }
QColorDialog QSpinBox::up-button,QColorDialog QSpinBox::down-button { width:0; border:0; }
QColorDialog QLineEdit { padding:4px 8px; }
QComboBox { background:#0d1621; border:1px solid #2c3a4a; border-radius:8px; padding:7px 36px 7px 12px; min-height:22px; min-width:150px; color:#e5edf2; }
QComboBox:hover { background:#122030; border-color:ACCENT; }
QComboBox:focus, QComboBox:on { border-color:ACCENT; }
QComboBox::drop-down { border:0; width:32px; subcontrol-origin:padding; subcontrol-position:center right; }
QComboBox::down-arrow { image:none; width:0; height:0; }
QComboBox QAbstractItemView { background:#111a25; border:1px solid #33445a; border-radius:10px; padding:5px; outline:0; selection-background-color:transparent; }
QComboBox QAbstractItemView::item { min-height:32px; padding:0 12px; border-radius:6px; color:#cfd9e3; }
QComboBox QAbstractItemView::item:hover { background:#1e2b3b; color:#ffffff; }
QComboBox QAbstractItemView::item:selected { background:#25344a; color:#ffffff; border-left:3px solid ACCENT; }
QLabel#statusPill { color:#c9d3df; background:#1b2634; border:1px solid #2f3e50; border-radius:10px; padding:3px 10px; font-size:12px; }
QCheckBox { spacing:10px; padding:6px 0; }
QCheckBox::indicator { width:18px; height:18px; border:1px solid #536272; border-radius:3px; background:#101922; }
QCheckBox::indicator:checked { background:ACCENT; border-color:ACCENT; image:none; }
QSlider::groove:horizontal { height:4px; background:#334453; border-radius:2px; }
QSlider::sub-page:horizontal { background:ACCENT; }
QSlider::handle:horizontal { width:14px; margin:-6px 0; background:#edf3f5; border-radius:7px; }
QScrollArea { border:0; background:transparent; }
QScrollBar:vertical { background:#0e1620; width:8px; }
QScrollBar::handle:vertical { background:#384959; border-radius:4px; min-height:35px; }
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height:0; }
QScrollBar:horizontal { background:transparent; height:8px; }
QScrollBar::handle:horizontal { background:ACCENT; border-radius:4px; min-width:32px; }
QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal { width:0; }
QScrollBar::add-page:horizontal,QScrollBar::sub-page:horizontal { background:transparent; }
QPlainTextEdit { background:#09121c; border:1px solid #304253; border-radius:6px; padding:12px; }
QMenu { background:#142130; border:1px solid #405164; }
QMenu::item { padding:8px 22px; } QMenu::item:selected { background:#304355; }
"""


def label(text, object_name=None):
    widget = QLabel(text)
    if object_name:
        widget.setObjectName(object_name)
    return widget


TacticalButton = AnimatedButton


def button(text, fn, primary=False):
    b = TacticalButton(text)
    b.setCursor(Qt.PointingHandCursor)
    b.clicked.connect(fn)
    if primary:
        b.setObjectName("primary")
    return b


def card(title):
    frame = GlowCard()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(8)
    layout.addWidget(label(title, "cardTitle"))
    return frame, layout


class ThemeTile(AnimatedButton):
    def __init__(self, name, dashboard):
        super().__init__("")
        self.name, self.dashboard = name, dashboard
        self.setCheckable(True)
        self.setMinimumHeight(130)
        self.setAccessibleName(name + " theme")
        self.clicked.connect(lambda: dashboard.select_theme(name))
        self.art = ScaledArt(limit=2)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        spec = THEMES[self.name]
        p.setBrush(QColor(spec.surface))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(self.rect()), 8, 8)
        phase = time.perf_counter() if self.underMouse() and self.dashboard.cfg["animations"] else 0
        paint_motif(p, QRectF(self.rect()), spec, phase)
        hero = self.dashboard.hero
        pix = hero.pixmaps.get(spec.agent or ("omen" if self.name == "Obsidian" else "jett"))
        if self.name == "Obsidian":
            pix = hero.shadow_pixmap
        if pix and not pix.isNull():
            p.save()
            p.setOpacity(0.9)
            dest = QRectF(self.width() * 0.42, 0, self.width() * 0.58, self.height())
            src = QRectF(
                (pix.width() - pix.height() * dest.width() / dest.height()) * 0.5,
                0,
                pix.height() * dest.width() / dest.height(),
                pix.height(),
            )
            self.art.draw(p, self.name, pix, dest, src)
            p.restore()
            blend = QLinearGradient(self.width() * 0.39, 0, self.width() * 0.65, 0)
            blend.setColorAt(0, QColor(spec.surface))
            transparent = QColor(spec.surface)
            transparent.setAlpha(0)
            blend.setColorAt(1, transparent)
            p.fillRect(dest, blend)
        p.setPen(QColor("#f4f1ed"))
        p.setFont(QFont("Bahnschrift", 14))
        p.drawText(16, 30, self.name.upper())
        p.setPen(QColor(spec.secondary))
        p.setFont(QFont("Segoe UI", 8))
        p.drawText(16, 51, spec.title)
        for i, color in enumerate((spec.accent, spec.secondary, spec.background)):
            p.setBrush(QColor(color))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(16 + i * 22, 76, 16, 6), 3, 3)
        color = QColor(spec.accent)
        color.setAlphaF(1 if self.isChecked() else 0.3 + 0.6 * self.hover_alpha)
        p.setPen(QPen(color, 2 if self.isChecked() else 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 8, 8)
        if self.isChecked():
            p.setFont(QFont("Segoe UI", 8))
            p.drawText(16, 111, "SELECTED")
        p.end()


class Dashboard(QMainWindow):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.cfg = controller.cfg.data
        self.controls = {}
        self.nav = []
        self.setWindowTitle("Spike AI")
        self.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint)
        self.setWindowIcon(QIcon(resource_path("assets", "logo", "spike-ai.ico")))
        available = QApplication.primaryScreen().availableGeometry()
        self.setFixedSize(
            min(1040, max(200, available.width() - 32)), min(700, max(120, available.height() - 55))
        )
        self.wheel_guard = WheelGuard(self)
        QApplication.instance().installEventFilter(self.wheel_guard)
        central = QWidget()
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(60)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 18, 12, 16)
        side.setSpacing(6)
        self.brand = BrandMark()
        side.addWidget(self.brand)
        side.addSpacing(22)
        for index, (name, icon) in enumerate(
            [
                ("Command center", "home"),
                ("General", "general"),
                ("Detection", "detection"),
                ("Overlay && alert", "overlay"),
                ("Audio && voices", "audio"),
                ("Appearance", "appearance"),
                ("Valorant Console", "console"),
                ("About", "about"),
            ]
        ):
            b = NavButton(name, icon)
            b.clicked.connect(lambda checked=False, i=index: self.navigate(i))
            side.addWidget(b)
            self.nav.append(b)
        side.addStretch()
        side.addWidget(button("Exit Spike AI", controller.close))
        sidebar_scroll = QScrollArea()
        sidebar_scroll.setFixedWidth(192 if available.width() > 800 else 156)
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sidebar_scroll.setWidget(sidebar)
        self.sidebar_scroll = sidebar_scroll
        outer.addWidget(sidebar_scroll)
        main = QWidget()
        main.setObjectName("page")
        area = QVBoxLayout(main)
        area.setContentsMargins(22, 16, 22, 14)
        area.setSpacing(12)
        bar = QHBoxLayout()
        bar.addWidget(ShimmerText("SPIKE AI  /  3.0", 11, spacing=2.5))
        bar.addStretch()
        self.activity = ActivityDot()
        bar.addWidget(self.activity)
        self.live = label("STANDBY", "muted")
        bar.addWidget(self.live)
        area.addLayout(bar)
        self.stack = QStackedWidget()
        area.addWidget(self.stack, 1)
        self.make_home()
        self.make_general()
        self.make_detection()
        self.make_overlay()
        self.make_voice()
        self.make_appearance()
        self.logs = LogViewer(self.cfg, controller.change_setting)
        self.logs.setMinimumSize(530, 420)
        self.logs_scroll = QScrollArea()
        self.logs_scroll.setWidgetResizable(True)
        self.logs_scroll.setWidget(self.logs)
        self.stack.addWidget(self.logs_scroll)
        self.make_about()
        for scroll in self.findChildren(QAbstractScrollArea):
            scroll.setVerticalScrollBar(AnimatedScrollBar(Qt.Vertical, scroll))
            scroll.setHorizontalScrollBar(AnimatedScrollBar(Qt.Horizontal, scroll))
        outer.addWidget(main, 1)
        self.adapt_navigation(available.width())
        self.apply_theme(animate=False)
        self.animated = None
        self.animated_at = 0.0
        self.effects_at = 0.0
        self.effect_timer = QTimer(self)
        self.effect_timer.setTimerType(Qt.PreciseTimer)
        self.effect_timer.setInterval(42)
        self.effect_timer.timeout.connect(self.animate_effects)
        self.effect_timer.start()
        self.navigate(0)
        self.tray = Tray(controller, self)
        self.tray.show()
        self.windowHandle().screenChanged.connect(self.fit_screen) if self.windowHandle() else None

    def adapt_navigation(self, width):
        self.compact_nav = width < 800
        self.sidebar_scroll.setFixedWidth(76 if self.compact_nav else 192)
        for b in self.nav:
            b.set_compact(self.compact_nav)
        self.brand.set_compact(self.compact_nav)

    def fit_screen(self, screen):
        available = screen.availableGeometry()
        self.adapt_navigation(available.width())
        self.setFixedSize(
            min(1040, max(200, available.width() - 32)), min(700, max(120, available.height() - 55))
        )

    def apply_theme(self, animate=True):
        app = QApplication.instance()
        spec = theme(self.cfg)
        previous_spec = getattr(self, "applied_spec", spec)
        self.applied_spec = spec
        app.setProperty("reduced_motion", not self.cfg["animations"])
        app.setProperty("rgb", self.cfg["theme"] == "RGB")
        old = QColor(app.property("accent") or spec.accent)
        app.setProperty("accent", self.cfg["accent"])
        app.setProperty("secondary", spec.secondary)
        if hasattr(self, "color_transition"):
            self.color_transition.stop()
            self.color_transition.deleteLater()

        def paint(value):
            target = QColor(self.cfg["accent"])
            color = QColor(
                *[round(old.getRgb()[i] + (target.getRgb()[i] - old.getRgb()[i]) * value) for i in range(3)]
            )

            def mix(before, after):
                a, b = QColor(before), QColor(after)
                return QColor(
                    *[round(a.getRgb()[i] + (b.getRgb()[i] - a.getRgb()[i]) * value) for i in range(3)]
                ).name()

            background = mix(previous_spec.background, spec.background)
            surface = mix(previous_spec.surface, spec.surface)
            sheet = STYLE.replace("ACCENT", color.name()).replace("BG", background)
            sheet = sheet.replace("#141e2a", surface).replace("#0b1119", background)
            sheet = sheet.replace("#1c2938", QColor(spec.surface).lighter(115).name()).replace(
                "#2a3b4e", QColor(spec.surface).lighter(135).name()
            )
            sheet = sheet.replace("#ff7681", QColor(spec.accent).lighter(115).name())
            self.setStyleSheet(
                sheet
                + """
                QLabel#cardTitle { font:600 13px 'Bahnschrift'; color:#b7c3d1; }
                QCheckBox#switch::indicator { width:36px; height:20px; border:0; background:transparent; }
                QCheckBox#switch::indicator:checked { background:transparent; border:0; }
                QScrollBar:vertical { background:transparent; width:9px; margin:3px 0; }
                QScrollBar::handle:vertical { background:"""
                + QColor(spec.accent).darker(190).name()
                + """; border-radius:4px; min-height:32px; }
                QScrollBar::handle:vertical:hover { background:"""
                + spec.accent
                + """; }
                QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical { background:transparent; }
                QPushButton { padding:9px 12px; border-radius:6px; }
                QPushButton:disabled { color:#737e8b; border-color:#343b48; background:#20242d; }
                QSlider::handle:horizontal:hover { background:"""
                + spec.secondary
                + """; }
            """
            )

        self.color_transition = QVariantAnimation(self)
        self.color_transition.setDuration(240)
        self.color_transition.setStartValue(0.0)
        self.color_transition.setEndValue(1.0)
        self.color_transition.valueChanged.connect(paint)
        if animate and self.cfg["animations"]:
            self.color_transition.start()
        else:
            paint(1.0)
        for tile in getattr(self, "theme_tiles", {}).values():
            tile.setChecked(tile.name == self.cfg["theme"])
            tile.update()
        if self.cfg["high_contrast"]:
            self.setStyleSheet(
                self.styleSheet()
                + "QLabel#muted { color:#dbe2ec; } QFrame#card { border-color:#8291a4; } QPushButton { border-color:#8291a4; }"
            )
        for widget in self.findChildren(ShimmerText) + [self.brand]:
            widget.update()
        self.hero.transition_theme()
        self.hero.update()

    def select_theme(self, name):
        self.cfg["accent"] = THEMES[name].accent
        self.cfg["edge_color"] = THEMES[name].accent
        self.controller.change_setting("theme", name)

    def animated_widgets(self):
        now = time.perf_counter()
        if self.animated is None or now - self.animated_at > 2:
            self.animated = (
                [w for w in self.findChildren(AnimatedButton) if not isinstance(w, ThemeTile)],
                self.findChildren(GlowCard),
                self.findChildren(ShimmerText) + [self.brand],
            )
            self.animated_at = now
        return self.animated

    def effects_due(self):
        return self.isVisible() and not self.isMinimized() and bool(self.cfg["animations"])

    def animate_effects(self):
        if not self.effects_due():
            self.hero.pause()
            self.effect_timer.stop()
            return
        now = time.perf_counter()
        if self.stack.currentIndex() == 0:
            self.hero.advance()
            self.effect_timer.setInterval(16 if self.hero.transitioning() else 42)
            if now - self.effects_at < 0.038:
                return
        else:
            self.hero.pause()
            self.effect_timer.setInterval(42)
        self.effects_at = now
        if self.stack.currentIndex() == 5:
            for tile in self.theme_tiles.values():
                if tile.underMouse():
                    tile.update()
        self.activity.update()
        if self.cfg["theme"] == "RGB":
            buttons, cards, captions = self.animated_widgets()
            for widget in buttons:
                if widget.isVisible() and (widget.underMouse() or widget.isChecked()):
                    widget.update()
            for frame in cards:
                if frame.isVisible():
                    frame.update_border()
            for widget in captions:
                if widget.isVisible():
                    widget.update()

    def make_about(self):
        layout = self.page("About")
        box, inner = card("Spike AI")
        layout.addWidget(box)
        inner.addWidget(label("Version " + __version__, "cardValue"))
        notice = label(
            "The countdown shows the time left to start a full defuse (7 s), not the time until the Spike detonates.",
            "muted",
        )
        notice.setWordWrap(True)
        inner.addWidget(notice)
        inner.addWidget(label("Created by Kira Kohler", "credit"))
        box, inner = card("Licenses & Legal")
        layout.addWidget(box)
        inner.addWidget(label(DISCLAIMER_TITLE, "legalTitle"))
        self.disclaimer = []
        for paragraph in DISCLAIMER:
            text = label(paragraph, "legalText")
            text.setWordWrap(True)
            text.setTextInteractionFlags(Qt.TextSelectableByMouse)
            inner.addWidget(text)
            self.disclaimer.append(text)
        row = QHBoxLayout()
        row.addWidget(button("View licenses", self.show_legal))
        row.addStretch()
        inner.addLayout(row)
        layout.addStretch()

    def show_legal(self):
        dialog = LegalDialog(self)
        self.legal_dialog = dialog
        dialog.exec()
        self.legal_dialog = None

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, "effect_timer") and self.effects_due():
            self.effect_timer.start()
        if not getattr(self, "screen_connected", False) and self.windowHandle():
            self.windowHandle().screenChanged.connect(self.fit_screen)
            self.screen_connected = True

    def changeEvent(self, event):
        from PySide6.QtCore import QEvent

        if event.type() == QEvent.WindowStateChange:
            if self.isMaximized() or self.isFullScreen():
                QTimer.singleShot(0, self.showNormal)
            if hasattr(self, "effect_timer") and self.effects_due() and not self.effect_timer.isActive():
                self.effect_timer.start()
            if hasattr(self, "stack") and self.stack.currentIndex() == 3:
                if self.isMinimized():
                    self.controller.config_overlay.hide()
                    self.controller.config_edge.hide()
                else:
                    self.controller.update_config_preview()
        super().changeEvent(event)

    def reveal(self):
        if self.controller.closed:
            return
        self.showNormal()
        self.raise_()
        self.activateWindow()
        if self.stack.currentIndex() == 3 and not self.controller.config_preview:
            self.controller.configure_preview(True)

    def finish_transition(self, effect):
        if self.stack.graphicsEffect() is effect:
            self.stack.setGraphicsEffect(None)

    def navigate(self, index):
        self.animated = None
        if getattr(self, "transition", None):
            self.transition.stop()
            self.transition.deleteLater()
            self.transition = None
        if hasattr(self, "transition_page"):
            self.transition_page.move(0, 0)
        self.stack.setCurrentIndex(index)
        for i, b in enumerate(self.nav):
            b.setChecked(i == index)
        self.controller.configure_preview(index == 3)
        if index == 1 and hasattr(self.controller, "startup_service"):
            self.controller.startup_service.refresh()
        page = self.stack.currentWidget()
        self.transition_page = page
        if self.cfg["animations"]:
            effect = QGraphicsOpacityEffect(self.stack)
            self.stack.setGraphicsEffect(effect)
            self.transition = QParallelAnimationGroup(self)
            fade = QPropertyAnimation(effect, b"opacity", self.transition)
            fade.setStartValue(0.25)
            fade.setEndValue(1.0)
            fade.setDuration(240)
            slide = QPropertyAnimation(page, b"pos", self.transition)
            slide.setStartValue(QPoint(22, 0))
            slide.setEndValue(QPoint(0, 0))
            slide.setDuration(240)
            slide.setEasingCurve(QEasingCurve.OutCubic)
            self.transition.addAnimation(fade)
            self.transition.addAnimation(slide)
            self.transition.finished.connect(lambda e=effect: self.finish_transition(e))
            self.transition.start()
        else:
            self.stack.setGraphicsEffect(None)
            page.move(0, 0)

    def page(self, title):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        widget = QWidget()
        widget.setObjectName("page")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 6, 6, 16)
        layout.setSpacing(12)
        layout.addWidget(label(title, "pageTitle"))
        scroll.setWidget(widget)
        self.stack.addWidget(scroll)
        return layout

    def check(self, layout, text, key):
        c = AnimatedSwitch(text)
        c.setChecked(bool(self.cfg[key]))
        c.toggled.connect(lambda v: self.controller.change_setting(key, v))
        layout.addWidget(c)
        self.controls[key] = c
        return c

    def slider(self, layout, text, key, lo, hi, mult=1, suffix=""):
        row = QHBoxLayout()
        row.addWidget(label(text))
        value = label("", "muted")
        row.addStretch()
        row.addWidget(value)
        layout.addLayout(row)
        s = QSlider(Qt.Horizontal)
        s.setRange(lo, hi)
        s.setValue(round(self.cfg[key] * mult))
        s.setAccessibleName(text)

        def update(v):
            value.setText(f"{v / mult:.2f} Hz" if key == "edge_speed" else f"{v}{suffix}")
            self.controller.change_setting(key, v / mult if mult != 1 else v)

        value.setText(f"{s.value() / mult:.2f} Hz" if key == "edge_speed" else f"{s.value()}{suffix}")
        s.valueChanged.connect(update)
        layout.addWidget(s)
        self.controls[key] = s

    def combo(self, layout, text, key, choices):
        row = QHBoxLayout()
        row.addWidget(label(text))
        row.addStretch()
        c = StyledCombo()
        for title, value in choices:
            c.addItem(title, value)
        current = next((i for i, (_, v) in enumerate(choices) if str(v) == str(self.cfg[key])), 0)
        c.setCurrentIndex(current)
        c.setAccessibleName(text)
        c.currentIndexChanged.connect(lambda index: self.controller.change_setting(key, c.itemData(index)))
        row.addWidget(c)
        layout.addLayout(row)
        self.controls[key] = c
        return c

    def make_home(self):
        layout = self.page("Command center")
        self.hero = Hero(self.cfg)
        layout.addWidget(self.hero)
        stats = QHBoxLayout()
        self.stat_values = {}
        for key, title in [("detector", "VISUAL DETECTOR"), ("game", "VALORANT"), ("focus", "GAME FOCUS")]:
            box, inner = card(title)
            value = label("Waiting", "cardValue")
            value.setStyleSheet("font-size:16px;")
            inner.addWidget(value)
            self.stat_values[key] = value
            stats.addWidget(box)
        layout.addLayout(stats)
        box, inner = card("Session control")
        layout.addWidget(box)
        self.status = label("Initializing…", "muted")
        self.status.setWordWrap(True)
        inner.addWidget(self.status)
        row = QHBoxLayout()
        self.detect_button = button("Pause detection", self.controller.toggle_detection, True)
        row.addWidget(self.detect_button)
        row.addWidget(button("Preview · 38 s", lambda: self.controller.start_preview(38)))
        row.addWidget(button("Cancel timer", lambda: self.controller.stop_all()))
        inner.addLayout(row)
        self.monitor_status = label("", "muted")
        inner.addWidget(self.monitor_status)
        layout.addStretch()

    def make_general(self):
        layout = self.page("General")
        box, inner = card("Startup & session")
        layout.addWidget(box)
        row = QHBoxLayout()
        startup = AnimatedSwitch("Launch with Windows")
        startup.setChecked(bool(self.cfg["startup"]))
        startup.toggled.connect(lambda v: self.controller.change_setting("startup", v))
        self.controls["startup"] = startup
        row.addWidget(startup)
        row.addStretch()
        self.startup_status = label("Checking Windows…", "statusPill")
        row.addWidget(self.startup_status)
        inner.addLayout(row)
        self.check(inner, "Start minimized", "start_minimized")
        self.check(inner, "Minimize to system tray on close", "minimize_to_tray")
        self.check(inner, "Show tray notifications", "tray_notifications")
        displays = self.controller.monitors
        if len(displays) > 1:
            primary = next((m for m in displays if m.primary), None)
            if self.cfg["monitor"] == "primary" and primary:
                self.cfg["monitor"] = str(primary.index)
            choices = [("Automatic · game display", "auto")] + [
                (
                    f"Display {m.index} · {m.width} × {m.height}" + (" · primary" if m.primary else ""),
                    str(m.index),
                )
                for m in displays
            ]
            self.combo(inner, "Capture & overlay monitor", "monitor", choices)
        else:
            row = QHBoxLayout()
            row.addWidget(label("Capture & overlay monitor"))
            row.addStretch()
            only = displays[0] if displays else None
            row.addWidget(label(f"{only.width} × {only.height}" if only else "Main display", "muted"))
            inner.addLayout(row)
        box, inner = card("Shortcuts")
        layout.addWidget(box)
        self.hotkey = HotkeyField(self.cfg["hotkey"], "Start timer")
        self.cancel_hotkey = HotkeyField(self.cfg["cancel_hotkey"], "Cancel timer")
        for field in (self.hotkey, self.cancel_hotkey):
            row = QHBoxLayout()
            row.addWidget(label(field.title))
            row.addStretch()
            row.addWidget(field)
            field.clicked.connect(lambda checked=False, f=field: self.capture_hotkey(f))
            inner.addLayout(row)
        for title, combo in (("Open Spike AI", "ctrl+alt+s"), ("Exit Spike AI", "ctrl+alt+q")):
            row = QHBoxLayout()
            row.addWidget(label(title, "muted"))
            row.addStretch()
            row.addWidget(KeycapDisplay(combo))
            inner.addLayout(row)
        layout.addStretch()

    def set_startup_status(self, message):
        self.startup_status.setText(message)
        self.startup_status.setVisible(message not in ("On", "Off"))

    def capture_hotkey(self, field):
        if getattr(self, "hotkey_capture", None):
            return
        self.controller.suspend_hotkeys()

        def validate(combo):
            start = combo if field is self.hotkey else self.cfg["hotkey"]
            cancel = combo if field is self.cancel_hotkey else self.cfg["cancel_hotkey"]
            error = self.controller.try_hotkeys(start, cancel)
            if not error:
                field.set_value(combo)
            return error

        def finished():
            self.hotkey_capture = None
            self.controller.resume_hotkeys()

        self.hotkey_capture = HotkeyCapture(self.centralWidget(), field.title, field.value, validate)
        self.animated = None
        self.hotkey_capture.finished.connect(finished)

    def make_detection(self):
        layout = self.page("Visual detection")
        box, inner = card("Monitoring")
        layout.addWidget(box)
        self.check(inner, "Enable visual detection", "detection_enabled")
        self.check(inner, "Cancel after five seconds of observed absence", "absence_watch")
        inner.addWidget(
            label("Absence interval: 5.0 continuous seconds · Only while the game has focus", "muted")
        )
        self.check(inner, "Record detailed diagnostics", "debug")
        box, inner = card("Diagnostics")
        layout.addWidget(box)
        self.metrics = label("No captured frames yet.", "muted")
        self.metrics.setWordWrap(True)
        inner.addWidget(self.metrics)
        inner.addWidget(button("Open diagnostics folder", self.controller.open_diagnostics))
        layout.addStretch()

    def make_overlay(self):
        layout = self.page("Overlay & alert")
        box, inner = card("Timer")
        layout.addWidget(box)
        self.check(inner, "Compact mode", "overlay_compact")
        self.slider(inner, "Size", "overlay_scale", 70, 180, 100, "%")
        self.slider(inner, "Timer opacity", "overlay_opacity", 30, 100, 100, "%")
        row = QHBoxLayout()
        row.addWidget(button("Move overlay", self.controller.edit_overlay))
        row.addWidget(button("Reset position", self.controller.reset_position))
        row.addWidget(button("Finish positioning", self.controller.finish_edit))
        inner.addLayout(row)
        self.position_label = label("Automatic position", "muted")
        inner.addWidget(self.position_label)
        box, inner = card("Perimeter alert")
        layout.addWidget(box)
        self.check(inner, "Enable edge alert", "edge_enabled")
        self.combo(
            inner,
            "Trigger · seconds remaining",
            "edge_threshold",
            [("10 seconds", 10), ("5 seconds", 5), ("3 seconds", 3)],
        )
        self.slider(inner, "Glow intensity", "edge_intensity", 10, 100, 100, "%")
        self.slider(inner, "Edge opacity", "edge_opacity", 5, 65, 100, "%")
        self.slider(inner, "Edge thickness", "edge_thickness", 12, 100, 1, " px")
        self.slider(inner, "Pulse speed", "edge_speed", 20, 150, 100, " /100 Hz")
        self.check(inner, "Soft pulse (disable for steady light)", "edge_animations")
        inner.addWidget(button("Alert color", lambda: self.choose_color("edge_color")))
        hint = label(
            "Live preview: the timer and the perimeter glow stay on screen while this page is open.", "muted"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()

    def make_voice(self):
        layout = self.page("Audio & voices")
        box, inner = card("Audio mix")
        layout.addWidget(box)
        self.slider(inner, "Master volume", "volume", 0, 100, 100, "%")
        self.check(inner, "Mute all callouts", "muted")
        self.voice_selectors = {}
        names = {
            "spike_planted": ("01", "Spike planted", "At timer start"),
            "20_seconds": ("02", "20 seconds", "18 s after planting"),
            "10_seconds": ("03", "10 seconds", "28 s after planting"),
            "5_seconds": ("04", "5 seconds", "33 s after planting"),
        }
        for _, name in MARKS:
            number, title, subtitle = names[name]
            box, inner = card(number + " / " + title)
            layout.addWidget(box)
            row = QHBoxLayout()
            enabled = AnimatedSwitch("Enabled")
            enabled.setChecked(self.cfg["voice_enabled"].get(name, True))
            enabled.toggled.connect(lambda v, n=name: self.voice_enabled(n, v))
            row.addWidget(enabled)
            row.addStretch()
            row.addWidget(button("▶  Play", lambda checked=False, n=name: self.controller.voice.preview(n)))
            inner.addLayout(row)
            row = QHBoxLayout()
            selector = StyledCombo()
            selector.setMinimumWidth(180)
            self.voice_selectors[name] = selector
            row.addWidget(selector, 1)
            self.populate_voice(name)
            selector.currentIndexChanged.connect(lambda idx, n=name: self.select_voice(n))
            row.addWidget(button("Import WAV", lambda checked=False, n=name: self.import_voice(n)))
            row.addWidget(button("Restore", lambda checked=False, n=name: self.restore_voice(n)))
            inner.addLayout(row)
        layout.addStretch()

    def populate_voice(self, name):
        c = self.voice_selectors[name]
        c.blockSignals(True)
        c.clear()
        c.addItem("Heart — Female (US)", "")
        folder = self.controller.cfg.home / "voices"
        files = sorted(folder.glob("*.wav")) if folder.exists() else []
        selected = self.cfg["voice_files"].get(name, "")
        for f in files:
            c.addItem(f.stem, str(f))
        index = c.findData(selected)
        c.setCurrentIndex(max(0, index))
        c.blockSignals(False)

    def select_voice(self, name):
        self.cfg["voice_files"][name] = self.voice_selectors[name].currentData() or ""
        self.controller.update_voices()

    def voice_enabled(self, name, value):
        self.cfg["voice_enabled"][name] = value
        self.controller.update_voices()

    def import_voice(self, name):
        path, _ = QFileDialog.getOpenFileName(self, "Import local voice", "", "WAV PCM16 (*.wav)")
        if not path:
            return
        try:
            read_voice(path)
            folder = self.controller.cfg.home / "voices"
            folder.mkdir(parents=True, exist_ok=True)
            import hashlib

            content = Path(path).read_bytes()
            dest = folder / (Path(path).stem + "-" + hashlib.sha256(content).hexdigest()[:8] + ".wav")
            if dest.resolve() != Path(path).resolve():
                dest.write_bytes(content)
            self.cfg["voice_files"][name] = str(dest)
            self.controller.update_voices()
            for key in self.voice_selectors:
                self.populate_voice(key)
        except Exception as error:
            QMessageBox.warning(self, "Import failed", str(error))

    def restore_voice(self, name):
        self.cfg["voice_files"].pop(name, None)
        self.populate_voice(name)
        self.controller.update_voices()

    def make_appearance(self):
        layout = self.page("Appearance")
        grid = QGridLayout()
        grid.setSpacing(12)
        self.theme_tiles = {}
        for i, name in enumerate(THEMES):
            tile = ThemeTile(name, self)
            self.theme_tiles[name] = tile
            grid.addWidget(tile, i // 2, i % 2)
        layout.addLayout(grid)
        box, inner = card("Motion & accessibility")
        layout.addWidget(box)
        self.check(inner, "Enable animations", "animations")
        self.slider(inner, "Effect intensity", "animation_intensity", 0, 100, 100, "%")
        self.check(inner, "Background details", "effects")
        self.check(inner, "High contrast", "high_contrast")
        inner.addWidget(button("Custom accent", lambda: self.choose_color("accent")))
        layout.addStretch()

    def choose_color(self, key):
        color = QColorDialog.getColor(QColor(self.cfg[key]), self, "Choose color")
        if color.isValid():
            self.controller.change_setting(key, color.name())

    def update_state(self, remaining, focused, game):
        if remaining != self.hero.remaining:
            self.hero.remaining = remaining
            self.hero.update()
        if not self.isVisible():
            return
        if self.effects_due() and not self.effect_timer.isActive():
            self.effect_timer.start()
        c = self.controller
        self.stat_values["detector"].setText(
            "Error" if c.worker_failed else "Active" if self.cfg["detection_enabled"] else "Paused"
        )
        self.stat_values["game"].setText("Detected" if game else "Not detected")
        self.stat_values["focus"].setText(
            "Focused" if focused is True else "Unfocused" if focused is False else "Unknown"
        )
        self.status.setText(c.status_text)
        self.detect_button.setText("Pause detection" if self.cfg["detection_enabled"] else "Enable detection")
        self.live.setText("PREVIEW" if c.preview_timeline else "SPIKE PLANTED" if c.timeline else "STANDBY")
        self.monitor_status.setText(
            f"Display · {c.screen().geometry().width()} × {c.screen().geometry().height()}"
        )
        m = c.worker.metrics
        frames = m["frames"]
        self.metrics.setText(
            f"Frames analysed: {frames:,}  ·  Errors: {m['errors']}\nAverage detection: {m['process_ms_sum'] / max(1, frames):.2f} ms  ·  Average capture: {m['capture_ms_sum'] / max(1, frames):.2f} ms"
        )
        self.position_label.setText(
            "Custom position" if self.cfg["overlay_position"] else "Automatic position"
        )

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.controller.stop_preview()
        else:
            super().keyPressEvent(event)

    def hideEvent(self, event):
        super().hideEvent(event)
        if not event.spontaneous() and self.controller.config_preview:
            self.controller.configure_preview(False)

    def closeEvent(self, event):
        c = self.controller
        if not c.closed and not QApplication.instance().isSavingSession() and self.cfg["minimize_to_tray"]:
            event.ignore()
            c.hide_to_tray()
            return
        c.close()
        QApplication.instance().removeEventFilter(self.wheel_guard)
        event.accept()
