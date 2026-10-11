import math
import time
import numpy as np
from PySide6.QtCore import Qt, QVariantAnimation, QEasingCurve, QRectF, QPointF, QSize, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPen,
    QBrush,
    QLinearGradient,
    QFont,
    QFontMetricsF,
    QPainterPath,
    QImage,
)
from PySide6.QtWidgets import QPushButton, QComboBox, QWidget, QListView, QSizePolicy
from .resources import resource_path
from .widgets import AnimatedButton, accent, secondary, motion, rgb, ink, font, keycap_parts, paint_keycaps


def _animator(owner, duration, callback):
    animation = QVariantAnimation(owner)
    animation.setDuration(duration)
    animation.setEasingCurve(QEasingCurve.OutCubic)
    animation.valueChanged.connect(callback)
    return animation


def _run(animation, current, target, apply):
    animation.stop()
    if not motion():
        apply(target)
        return
    animation.setStartValue(float(current))
    animation.setEndValue(float(target))
    animation.start()


def _mix(a, b, t):
    a, b = QColor(a), QColor(b)
    return QColor(*[round(a.getRgb()[i] + (b.getRgb()[i] - a.getRgb()[i]) * t) for i in range(4)])


_LOGO_SOURCE = []
_LOGO_SIZES = {}
LOGO_SHADOW = np.array([44, 50, 62], np.float32)


def logo_layers(size):
    if not _LOGO_SOURCE:
        image = QImage(resource_path("assets", "logo", "spike-ai-mark.png")).convertToFormat(
            QImage.Format_RGBA8888
        )
        w, h = image.width(), image.height()
        pixels = np.frombuffer(image.constBits(), np.uint8).reshape(h, image.bytesPerLine())[:, : w * 4]
        pixels = pixels.reshape(h, w, 4).astype(np.float32)
        low, high, alpha = pixels[..., :3].min(-1), pixels[..., :3].max(-1), pixels[..., 3]
        shade = LOGO_SHADOW * (1 - low[..., None] / 255) + low[..., None]
        neutral = np.dstack([shade, alpha]).astype(np.uint8)
        chroma = np.dstack([np.full_like(low, 255)] * 3 + [(high - low) / 255 * alpha]).astype(np.uint8)
        for layer in (neutral, chroma):
            data = np.ascontiguousarray(layer).tobytes()
            _LOGO_SOURCE.append(QImage(data, w, h, w * 4, QImage.Format_RGBA8888).copy())
    if size not in _LOGO_SIZES:
        scaled = []
        for image in _LOGO_SOURCE:
            while image.width() > size * 2:
                image = image.scaled(
                    image.width() // 2, image.height() // 2, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            scaled.append(image.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        _LOGO_SIZES[size] = scaled
    return _LOGO_SIZES[size]


def paint_logo(p, rect):
    size = max(16, round(rect.width() * p.device().devicePixelRatioF()))
    neutral, chroma = logo_layers(size)
    tinted = QImage(chroma.size(), QImage.Format_ARGB32_Premultiplied)
    tinted.fill(Qt.transparent)
    q = QPainter(tinted)
    q.drawImage(0, 0, chroma)
    q.setCompositionMode(QPainter.CompositionMode_SourceIn)
    q.fillRect(tinted.rect(), QBrush(ink(0, 0, tinted.width(), tinted.height())))
    q.end()
    p.drawImage(rect, neutral)
    p.drawImage(rect, tinted)


def keycaps_width(parts, pixels):
    metrics = QFontMetricsF(font("Bahnschrift", pixels, QFont.DemiBold))
    widths = [max(metrics.horizontalAdvance(part) + 18, pixels + 16) for part in parts]
    return sum(widths) + (metrics.horizontalAdvance("+") + 10) * max(0, len(parts) - 1)


class ShimmerText(QWidget):
    def __init__(self, text, pixels=11, weight=QFont.DemiBold, spacing=2.0, color=None, family="Bahnschrift"):
        super().__init__()
        self._text = text
        self.color = color
        self.setFont(font(family, pixels, weight, spacing))
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setAccessibleName(text)

    def text(self):
        return self._text

    def setText(self, text):
        self._text = text
        self.setAccessibleName(text)
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        metrics = QFontMetricsF(self.font())
        return QSize(math.ceil(metrics.horizontalAdvance(self._text)) + 4, math.ceil(metrics.height()) + 2)

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(self.font())
        width = max(60.0, QFontMetricsF(self.font()).horizontalAdvance(self._text))
        p.setPen(QPen(QBrush(ink(0, 0, width, 0, self.color)), 1))
        p.drawText(QRectF(self.rect()), Qt.AlignLeft | Qt.AlignVCenter, self._text)
        p.end()


class BrandMark(QWidget):
    def __init__(self):
        super().__init__()
        self.compact = False
        self.setFixedHeight(50)
        self.setAccessibleName("Spike AI by Kira Kohler")

    def set_compact(self, value):
        self.compact = value
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        return QSize(44 if self.compact else 168, 50)

    def duo(self, x1, y1, x2, y2):
        if rgb():
            return ink(x1, y1, x2, y2)
        gradient = QLinearGradient(x1, y1, x2, y2)
        gradient.setColorAt(0, accent())
        gradient.setColorAt(1, secondary())
        return gradient

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if self.compact:
            paint_logo(p, QRectF((self.width() - 42) / 2, 4, 42, 42))
            p.end()
            return
        paint_logo(p, QRectF(-2, 4, 42, 42))
        x = 46
        title = font("Bahnschrift", 21, QFont.DemiBold, 2.5)
        metrics = QFontMetricsF(title)
        p.setFont(title)
        p.setPen(QColor("#f3f5f8"))
        p.drawText(QPointF(x, 26), "SPIKE")
        ai_x = x + metrics.horizontalAdvance("SPIKE ")
        p.setPen(QPen(QBrush(self.duo(ai_x, 0, ai_x + metrics.horizontalAdvance("AI"), 0)), 1))
        p.drawText(QPointF(ai_x, 26), "AI")
        p.fillRect(QRectF(x + 1, 37, 10, 2), QBrush(self.duo(x, 0, x + 12, 0)))
        p.setFont(font("Bahnschrift", 10, QFont.Normal, 1.8))
        p.setPen(QColor("#8d9ab0"))
        p.drawText(QPointF(x + 17, 41.5), "BY KIRA KOHLER")
        p.end()


def paint_nav_icon(p, name, brush):
    def dot(x, y, r):
        p.setBrush(brush)
        p.drawEllipse(QPointF(x, y), r, r)
        p.setBrush(Qt.NoBrush)

    if name == "home":
        for x, y in ((-8, -8), (1, -8), (-8, 1), (1, 1)):
            p.drawRoundedRect(QRectF(x, y, 7, 7), 2, 2)
        p.fillRect(QRectF(-6.2, -6.2, 3.4, 3.4), brush)
    elif name == "general":
        for y, knob in ((-5.5, -2.5), (0, 3.5), (5.5, -0.5)):
            p.drawLine(QPointF(-8, y), QPointF(8, y))
            dot(knob, y, 2.3)
    elif name == "detection":
        p.drawEllipse(QPointF(0, 0), 6, 6)
        for a, b in (((0, -9), (0, -3.5)), ((0, 3.5), (0, 9)), ((-9, 0), (-3.5, 0)), ((3.5, 0), (9, 0))):
            p.drawLine(QPointF(*a), QPointF(*b))
        dot(0, 0, 1.2)
    elif name == "overlay":
        p.drawRoundedRect(QRectF(-8.5, -7, 17, 12), 2.5, 2.5)
        p.drawLine(QPointF(-3.5, 8.5), QPointF(3.5, 8.5))
        p.fillRect(QRectF(1.5, -4.5, 4.5, 3.2), brush)
    elif name == "audio":
        speaker = QPainterPath(QPointF(-8, -3))
        for x, y in ((-4.5, -3), (0, -7), (0, 7), (-4.5, 3), (-8, 3)):
            speaker.lineTo(x, y)
        speaker.closeSubpath()
        p.drawPath(speaker)
        p.drawArc(QRectF(-2, -4, 7, 8), -55 * 16, 110 * 16)
        p.drawArc(QRectF(-2, -8, 11, 16), -55 * 16, 110 * 16)
    elif name == "appearance":
        palette = QPainterPath()
        palette.addEllipse(QPointF(0, 0), 8.5, 8)
        notch = QPainterPath()
        notch.addEllipse(QPointF(4.2, 4.2), 2.6, 2.6)
        p.drawPath(palette.subtracted(notch))
        for x, y in ((-4, -2.5), (-0.5, -5), (3.6, -3)):
            dot(x, y, 1.5)
        dot(-3.2, 2.8, 1.5)
    elif name == "console":
        p.drawRoundedRect(QRectF(-9, -7.5, 18, 15), 2.8, 2.8)
        p.drawPolyline([QPointF(-5, -2.5), QPointF(-1.8, 0.5), QPointF(-5, 3.5)])
        p.drawLine(QPointF(0.5, 3.5), QPointF(5, 3.5))
    elif name == "about":
        p.drawEllipse(QPointF(0, 0), 8.5, 8.5)
        dot(0, -4, 1.2)
        p.drawLine(QPointF(0, -1), QPointF(0, 4.5))


class NavButton(AnimatedButton):
    def __init__(self, text, icon):
        super().__init__(text)
        self.full_text, self.icon = text, icon
        self.compact = False
        self.setObjectName("nav")
        self.setCheckable(True)
        self.setAccessibleName(text.replace("&&", "&"))

    def set_compact(self, compact):
        self.compact = compact
        self.setText("" if compact else self.full_text)

    def paintEvent(self, event):
        QPushButton.paintEvent(self, event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx = self.width() / 2 if self.compact else 28
        cy = self.height() / 2
        if self.isChecked():
            brush = QBrush(ink(cx - 9, cy - 9, cx + 9, cy + 9))
        else:
            brush = QBrush(_mix("#7f90a5", "#ffffff", self.hover_alpha))
        p.translate(cx, cy)
        p.setPen(QPen(brush, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        paint_nav_icon(p, self.icon, brush)
        p.end()


class StyledCombo(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setView(QListView())
        self.view().setMouseTracking(True)
        container = self.view().window()
        container.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        container.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.hover = self.turn = 0.0
        self.hover_animation = _animator(self, 200, self._hover)
        self.turn_animation = _animator(self, 220, self._turn)

    def _hover(self, value):
        self.hover = float(value)
        self.update()

    def _turn(self, value):
        self.turn = float(value)
        self.update()

    def enterEvent(self, event):
        _run(self.hover_animation, self.hover, 1, self._hover)
        super().enterEvent(event)

    def leaveEvent(self, event):
        _run(self.hover_animation, self.hover, 0, self._hover)
        super().leaveEvent(event)

    def showPopup(self):
        super().showPopup()
        _run(self.turn_animation, self.turn, 1, self._turn)

    def hidePopup(self):
        super().hidePopup()
        _run(self.turn_animation, self.turn, 0, self._turn)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        color = _mix("#7d8da1", accent(), max(self.hover, self.turn))
        p.setPen(QPen(color, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.translate(self.width() - 18, self.height() / 2)
        p.rotate(180 * self.turn)
        p.drawPolyline([QPointF(-4.5, -2.2), QPointF(0, 2.3), QPointF(4.5, -2.2)])
        p.end()


class KeycapDisplay(QWidget):
    def __init__(self, combo):
        super().__init__()
        self.parts = keycap_parts(combo)
        self.setFixedHeight(34)
        self.setAccessibleName(" + ".join(self.parts))

    def sizeHint(self):
        return QSize(math.ceil(keycaps_width(self.parts, 12)) + 4, 34)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        paint_keycaps(p, self.parts, self.width() - 2, self.height() / 2 - 1, pixels=12, align_right=True)
        p.end()


class HotkeyField(QPushButton):
    def __init__(self, value, title):
        super().__init__()
        self.setObjectName("hotkeyField")
        self.value, self.title = value, title
        self.hover = 0.0
        self.hover_animation = _animator(self, 200, self._hover)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setMinimumSize(230, 44)
        self.set_value(value)

    def _hover(self, value):
        self.hover = float(value)
        self.update()

    def set_value(self, value):
        self.value = value
        self.setAccessibleName(f"{self.title}: {' + '.join(keycap_parts(value))}")
        self.update()

    def enterEvent(self, event):
        _run(self.hover_animation, self.hover, 1, self._hover)
        super().enterEvent(event)

    def leaveEvent(self, event):
        _run(self.hover_animation, self.hover, 0, self._hover)
        super().leaveEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setBrush(_mix("#0d1621", "#122030", self.hover))
        border = accent() if self.hasFocus() else _mix("#2c3a4a", accent(), self.hover)
        p.setPen(QPen(border, 1.2))
        p.drawRoundedRect(r, 8, 8)
        paint_keycaps(p, keycap_parts(self.value), r.left() + 10, r.center().y() - 1, pixels=12)
        hint = QColor("#8d9ab0")
        hint.setAlphaF(0.55 + 0.45 * self.hover)
        p.setPen(hint)
        p.setFont(font("Segoe UI", 12))
        p.drawText(r.adjusted(0, 0, -14, 0), Qt.AlignRight | Qt.AlignVCenter, "Change")
        p.end()


def key_name(event):
    vk = event.nativeVirtualKey()
    if 0x70 <= vk <= 0x87:
        return f"f{vk - 0x6F}"
    if 0x41 <= vk <= 0x5A or 0x30 <= vk <= 0x39:
        return chr(vk).lower()
    key = event.key()
    f1, f24 = Qt.Key_F1.value, Qt.Key_F24.value
    if f1 <= key <= f24:
        return f"f{key - f1 + 1}"
    if Qt.Key_A.value <= key <= Qt.Key_Z.value or Qt.Key_0.value <= key <= Qt.Key_9.value:
        return chr(key).lower()
    return None


def modifier_names(modifiers):
    return [
        name
        for flag, name in (
            (Qt.ControlModifier, "ctrl"),
            (Qt.AltModifier, "alt"),
            (Qt.ShiftModifier, "shift"),
            (Qt.MetaModifier, "win"),
        )
        if modifiers & flag
    ]


MODIFIER_KEYS = {k.value for k in (Qt.Key_Control, Qt.Key_Alt, Qt.Key_Shift, Qt.Key_Meta, Qt.Key_AltGr)}


class HotkeyCapture(QWidget):
    finished = Signal()

    def __init__(self, host, title, current, validate):
        super().__init__(host)
        self.validate, self.title, self.current = validate, title, current
        self.parts, self.error, self.done = [], "", False
        self.fade = self.shake = 0.0
        self.closing = False
        self.setGeometry(host.rect())
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("Press the new shortcut for " + title)
        self.cancel = AnimatedButton("Cancel", self)
        self.cancel.setFocusPolicy(Qt.NoFocus)
        self.cancel.clicked.connect(self.dismiss)
        self.fade_animation = _animator(self, 190, self._fade)
        self.shake_animation = QVariantAnimation(self)
        self.shake_animation.setDuration(360)
        self.shake_animation.setStartValue(0.0)
        self.shake_animation.setEndValue(1.0)
        self.shake_animation.valueChanged.connect(self._shake)
        self.ticker = QTimer(self)
        self.ticker.setInterval(33)
        self.ticker.timeout.connect(self.update)
        self.ticker.start()
        self.show()
        self.raise_()
        self.setFocus()
        self.grabKeyboard()
        _run(self.fade_animation, 0, 1, self._fade)

    def _fade(self, value):
        self.fade = float(value)
        if self.closing and self.fade <= 0.001:
            self.deleteLater()
        self.update()

    def _shake(self, value):
        self.shake = float(value)
        self.update()

    def card(self):
        w, h = 440, 268
        offset = math.sin(self.shake * math.pi * 6) * (1 - self.shake) * 9
        return QRectF((self.width() - w) / 2 + offset, (self.height() - h) / 2 + (1 - self.fade) * 16, w, h)

    def place_button(self):
        card = self.card()
        self.cancel.setFixedSize(108, 36)
        self.cancel.move(round(card.right() - 132), round(card.bottom() - 54))

    def paintEvent(self, event):
        self.place_button()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(3, 5, 9, round(175 * self.fade)))
        p.setOpacity(self.fade)
        card = self.card()
        p.setBrush(QColor("#131b26"))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(card, 14, 14)
        if self.error:
            border = QBrush(QColor("#ff5d6c"))
        elif self.done:
            border = QBrush(QColor("#5fe0a8"))
        else:
            border = QBrush(ink(card.left(), card.top(), card.right(), card.bottom()))
        p.setPen(QPen(border, 1.6))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(card.adjusted(0.8, 0.8, -0.8, -0.8), 14, 14)
        left = card.left() + 26
        p.setFont(font("Bahnschrift", 11, QFont.DemiBold, 2.5))
        p.setPen(QPen(QBrush(ink(left, 0, left + 200, 0)), 1))
        p.drawText(QPointF(left, card.top() + 34), "SHORTCUT · " + self.title.upper())
        p.setFont(font("Bahnschrift", 23, QFont.DemiBold))
        p.setPen(QColor("#f4f6f9"))
        p.drawText(
            QPointF(left, card.top() + 66), "Shortcut saved" if self.done else "Press the new shortcut"
        )
        p.setFont(font("Segoe UI", 12))
        p.setPen(QColor("#8d9ab0"))
        p.drawText(QPointF(left, card.top() + 88), "Current: " + " + ".join(keycap_parts(self.current)))
        zone = QRectF(left, card.top() + 104, card.width() - 52, 64)
        pulse = 0.5 + 0.5 * math.sin(time.perf_counter() * 4) if motion() and not self.parts else 1
        edge = QColor("#ff5d6c" if self.error else "#5fe0a8" if self.done else "#3a4b5f")
        edge.setAlphaF(0.45 + 0.55 * pulse)
        p.setPen(QPen(edge, 1.2, Qt.DashLine))
        p.setBrush(QColor("#0c131c"))
        p.drawRoundedRect(zone, 10, 10)
        if self.parts:
            width = keycaps_width(self.parts, 15)
            highlight = QColor("#5fe0a8") if self.done else QColor("#ff5d6c") if self.error else accent()
            paint_keycaps(p, self.parts, zone.center().x() - width / 2, zone.center().y() - 1, highlight, 15)
        else:
            waiting = QColor("#8d9ab0")
            waiting.setAlphaF(0.5 + 0.5 * pulse)
            p.setPen(waiting)
            p.setFont(font("Segoe UI", 13))
            p.drawText(zone, Qt.AlignCenter, "Waiting for a key…")
        p.setFont(font("Segoe UI", 11))
        if self.error:
            p.setPen(QColor("#ff8a95"))
            message = self.error
        else:
            p.setPen(QColor("#6f7f92"))
            message = "F1–F24, A–Z or 0–9 · optional Ctrl, Alt, Shift, Win\nEsc to cancel"
        p.drawText(
            QRectF(left, zone.bottom() + 10, card.width() - 190, 48), Qt.AlignLeft | Qt.TextWordWrap, message
        )
        p.end()

    def keyPressEvent(self, event):
        event.accept()
        if self.done or self.closing or event.isAutoRepeat():
            return
        modifiers = modifier_names(event.modifiers())
        if event.key() == Qt.Key_Escape.value and not modifiers:
            self.dismiss()
            return
        if event.key() in MODIFIER_KEYS:
            self.parts, self.error = keycap_parts("+".join(modifiers)), ""
            self.update()
            return
        name = key_name(event)
        if name is None:
            self.parts = keycap_parts("+".join(modifiers + ["?"]))
            self.fail("That key cannot be used. Choose F1–F24, a letter or a number.")
            return
        combo = "+".join(modifiers + [name])
        self.parts = keycap_parts(combo)
        error = self.validate(combo)
        if error:
            self.fail(error)
            return
        self.error, self.done = "", True
        self.cancel.hide()
        self.update()
        QTimer.singleShot(520, self.dismiss)

    def keyReleaseEvent(self, event):
        event.accept()
        if not self.done and not self.error and event.key() in MODIFIER_KEYS:
            self.parts = keycap_parts("+".join(modifier_names(event.modifiers())))
            self.update()

    def fail(self, message):
        self.error = message
        self.shake_animation.stop()
        if motion():
            self.shake_animation.start()
        self.update()

    def mousePressEvent(self, event):
        event.accept()
        if not self.card().contains(event.position()):
            self.dismiss()

    def dismiss(self):
        if self.closing:
            return
        self.closing = True
        self.releaseKeyboard()
        self.finished.emit()
        if motion():
            self.fade_animation.setDuration(150)
            _run(self.fade_animation, self.fade, 0, self._fade)
        else:
            self.deleteLater()
