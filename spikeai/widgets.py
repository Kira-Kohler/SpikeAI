import math
import time
from PySide6.QtCore import Qt, QEvent, QObject, QVariantAnimation, QEasingCurve, QRectF
from PySide6.QtGui import (
    QRegion,
    QColor,
    QPainter,
    QPen,
    QBrush,
    QConicalGradient,
    QLinearGradient,
    QFont,
    QFontMetricsF,
)
from PySide6.QtWidgets import (
    QApplication,
    QPushButton,
    QCheckBox,
    QSlider,
    QComboBox,
    QAbstractSpinBox,
    QScrollArea,
    QFrame,
    QScrollBar,
)


def accent():
    app = QApplication.instance()
    if app.property("rgb") and not app.property("reduced_motion"):
        return QColor.fromHsvF((time.perf_counter() / 9) % 1, 0.55, 1)
    return QColor(app.property("accent") or "#ff4655")


def secondary():
    return QColor(QApplication.instance().property("secondary") or "#ffb05c")


def motion():
    app = QApplication.instance()
    return not app.property("reduced_motion")


def rgb():
    return bool(QApplication.instance().property("rgb"))


def flowing(x1, y1, x2, y2, saturation=0.6, value=1.0, speed=0.22):
    shift = time.perf_counter() * speed if motion() else 0
    gradient = QLinearGradient(x1, y1, x2, y2)
    for i in range(7):
        gradient.setColorAt(i / 6, QColor.fromHsvF((i / 6 - shift) % 1, saturation, value))
    return gradient


def ink(x1, y1, x2, y2, fallback=None):
    if rgb():
        return flowing(x1, y1, x2, y2)
    return QColor(fallback) if fallback else accent()


def font(family, pixels, weight=QFont.Normal, spacing=0.0):
    f = QFont(family)
    f.setPixelSize(pixels)
    f.setWeight(weight)
    if spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return f


def keycap_parts(text):
    names = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win"}
    return [names.get(part, part.upper()) for part in text.lower().replace(" ", "").split("+") if part]


def paint_keycaps(p, parts, x, cy, highlight=None, pixels=13, align_right=False):
    f = font("Bahnschrift", pixels, QFont.DemiBold)
    metrics = QFontMetricsF(f)
    widths = [max(metrics.horizontalAdvance(part) + 18, pixels + 16) for part in parts]
    plus = metrics.horizontalAdvance("+") + 10
    total = sum(widths) + plus * max(0, len(parts) - 1)
    left = x - total if align_right else x
    h = pixels + 16
    p.setFont(f)
    for i, (part, width) in enumerate(zip(parts, widths)):
        cap = QRectF(left, cy - h / 2, width, h)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#070b11"))
        p.drawRoundedRect(cap.translated(0, 2), 6, 6)
        p.setBrush(QColor("#1d2a3a"))
        p.drawRoundedRect(cap, 6, 6)
        edge = QBrush(highlight) if highlight is not None else QBrush(QColor("#3b4d61"))
        p.setPen(QPen(edge, 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(cap.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        p.setPen(QColor("#f1f4f8"))
        p.drawText(cap, Qt.AlignCenter, part)
        left += width
        if i < len(parts) - 1:
            p.setPen(QColor("#6f7f92"))
            p.drawText(QRectF(left, cy - h / 2, plus, h), Qt.AlignCenter, "+")
            left += plus
    return total


class AnimatedButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.hover_alpha = 0.0
        self.hover_animation = QVariantAnimation(self)
        self.hover_animation.setDuration(230)
        self.hover_animation.setEasingCurve(QEasingCurve.OutCubic)
        self.hover_animation.valueChanged.connect(self.animate_hover)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.keyboard_focus = False

    def focusInEvent(self, event):
        self.keyboard_focus = event.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason)
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self.keyboard_focus = False
        super().focusOutEvent(event)

    def animate_hover(self, value):
        self.hover_alpha = float(value)
        self.update()

    def transition_hover(self, value):
        self.hover_animation.stop()
        if not motion():
            self.animate_hover(value)
            return
        self.hover_animation.setStartValue(self.hover_alpha)
        self.hover_animation.setEndValue(value)
        self.hover_animation.start()

    def enterEvent(self, event):
        self.transition_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.transition_hover(0.0)
        super().leaveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.isEnabled():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = accent()
        focused = self.hasFocus() and self.keyboard_focus
        if self.hover_alpha or focused or self.isDown():
            c.setAlphaF(0.08 + 0.18 * self.hover_alpha if not self.isDown() else 0.32)
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            inset = 3 if self.isDown() else 1
            p.drawRoundedRect(QRectF(self.rect()).adjusted(inset, inset, -inset, -inset), 6, 6)
            c.setAlphaF(0.45 + 0.5 * self.hover_alpha)
            p.setPen(QPen(c, 2 if focused else 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 6, 6)
        p.end()


class AnimatedSwitch(QCheckBox):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setObjectName("switch")
        self.level = 0.0
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(220)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.animation.valueChanged.connect(self.frame)
        self.toggled.connect(self.transition)
        self.setCursor(Qt.PointingHandCursor)

    def frame(self, value):
        self.level = float(value)
        self.update()

    def transition(self, on):
        self.animation.stop()
        target = float(on)
        if not motion() or not self.isVisible():
            self.frame(target)
            return
        self.animation.setStartValue(self.level)
        self.animation.setEndValue(target)
        self.animation.start()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(0, (self.height() - 20) / 2, 36, 20)
        c = accent() if self.isChecked() else QColor("#435062")
        if not self.isEnabled():
            c.setAlpha(85)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(rect, 10, 10)
        p.setBrush(QColor("#f0f2f4"))
        p.drawEllipse(QRectF(3 + 16 * self.level, rect.y() + 3, 14, 14))
        p.end()


class GlowCard(QFrame):
    def __init__(self):
        super().__init__()
        self.level = 0.0
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(250)
        self.animation.valueChanged.connect(self.frame)
        self.setAttribute(Qt.WA_Hover)

    def frame(self, v):
        self.level = float(v)
        self.update()

    def animate(self, target):
        self.animation.stop()
        if not motion():
            self.frame(target)
            return
        self.animation.setStartValue(self.level)
        self.animation.setEndValue(target)
        self.animation.start()

    def enterEvent(self, event):
        self.animate(1)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.animate(0)
        super().leaveEvent(event)

    def update_border(self):
        rect = self.rect()
        self.update(QRegion(rect).subtracted(QRegion(rect.adjusted(6, 6, -6, -6))))

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.level or rgb():
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            c = accent()
            c.setAlphaF(0.15 + 0.5 * self.level)
            if rgb():
                t = time.perf_counter() if motion() else 0
                gradient = QConicalGradient(QRectF(self.rect()).center(), (-t * 75) % 360)
                for i in range(13):
                    gradient.setColorAt(i / 12, QColor.fromHsvF((i / 12 + t * 0.12) % 1, 0.62, 1))
                p.setPen(QPen(QBrush(gradient), 1.6 + 0.8 * self.level))
            else:
                p.setPen(QPen(c, 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 8, 8)
            p.end()


class WheelGuard(QObject):
    def eventFilter(self, obj, event):
        if event.type() != QEvent.Wheel or not isinstance(obj, (QSlider, QComboBox, QAbstractSpinBox)):
            return False
        if isinstance(obj, QComboBox) and obj.view().isVisible():
            return False
        parent = obj.parentWidget()
        while parent and not isinstance(parent, QScrollArea):
            parent = parent.parentWidget()
        if parent:
            bar = parent.verticalScrollBar()
            pixels = event.pixelDelta().y()
            delta = pixels if pixels else event.angleDelta().y() / 120 * bar.singleStep() * 3
            bar.setValue(bar.value() - round(delta))
        event.accept()
        return True


class ActivityDot(QFrame):
    def __init__(self):
        super().__init__()
        self.setFixedSize(12, 12)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = accent()
        pulse = 0.75 + 0.25 * math.sin(time.perf_counter() * 3) if motion() else 1
        c.setAlphaF(pulse)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawEllipse(QRectF(2, 2, 8, 8))
        p.end()


class AnimatedScrollBar(QScrollBar):
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.glow = 0.0
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(200)
        self.animation.valueChanged.connect(self.frame)

    def frame(self, value):
        self.glow = float(value)
        self.update()

    def animate(self, value):
        self.animation.stop()
        if not motion():
            self.frame(value)
            return
        self.animation.setStartValue(self.glow)
        self.animation.setEndValue(value)
        self.animation.start()

    def enterEvent(self, event):
        self.animate(1)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.animate(0)
        super().leaveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.glow:
            p = QPainter(self)
            c = accent()
            c.setAlphaF(self.glow * 0.22)
            p.fillRect(self.rect(), c)
            p.end()
