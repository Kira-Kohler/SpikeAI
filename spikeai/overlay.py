import math
import time
import ctypes
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QFont, QPainterPath, QLinearGradient, QRadialGradient
from PySide6.QtWidgets import QWidget, QApplication


def urgency(remaining):
    return (
        "#ff4655"
        if remaining <= 5
        else "#ffac69"
        if remaining <= 10
        else "#ead3a2"
        if remaining <= 20
        else "#7de2d1"
    )


def edge_due(remaining, focused, config, preview=False):
    return bool(
        config["edge_enabled"]
        and remaining is not None
        and 0 < remaining <= config["edge_threshold"]
        and (focused is True or preview)
    )


def edge_strength(config):
    return min(0.95, (0.2 + 1.15 * config["edge_opacity"]) * (0.55 + 0.65 * config["edge_intensity"]))


def surface(interactive=False):
    flags = Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
    if not interactive:
        flags |= Qt.WindowTransparentForInput
    return flags


_user32 = None


def _user():
    global _user32
    if _user32 is None:
        from ctypes import wintypes

        user = ctypes.WinDLL("user32", use_last_error=True)
        user.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user.GetWindowLongW.restype = ctypes.c_long
        user.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        user.SetWindowLongW.restype = ctypes.c_long
        _user32 = user
    return _user32


def native_no_activate(widget, transparent=True):
    import sys

    if sys.platform != "win32":
        return
    user = _user()
    hwnd = int(widget.winId())
    style = user.GetWindowLongW(hwnd, -20) | 0x08000000
    style = style | 0x80020 if transparent else style & ~0x20
    user.SetWindowLongW(hwnd, -20, style)


class Overlay(QWidget):
    def __init__(self, config, on_moved=None):
        super().__init__(None, surface())
        self.setWindowTitle("Spike AI · Timer")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.config, self.on_moved = config, on_moved
        self.remaining = 38.0
        self.preview = False
        self.editable = False
        self.drag = None
        self.appeared = time.perf_counter()
        self.on_painted = None
        self.paint_pending = False
        self.drawn_key = None
        self.opacity_level = 1.0
        self.fonts = (
            QFont("Bahnschrift", 8),
            QFont("Bahnschrift SemiBold", 28),
            QFont("Bahnschrift", 9),
            QFont("Bahnschrift", 7),
        )
        self.apply_config()

    def prewarm(self):
        image = QImage(self.size(), QImage.Format_ARGB32_Premultiplied)
        image.fill(0)
        QWidget.render(self, image)
        opacity = self.windowOpacity()
        self.setWindowOpacity(0.0)
        QWidget.show(self)
        self.repaint()
        QWidget.hide(self)
        self.setWindowOpacity(opacity)

    @property
    def visible(self):
        return self.isVisible()

    def apply_config(self):
        self.drawn_key = None
        s = float(self.config["overlay_scale"])
        self.setFixedSize(round((178 if self.config["overlay_compact"] else 268) * s), round(86 * s))
        self.setWindowOpacity(self.config["overlay_opacity"])
        self.update()

    def set_editable(self, value):
        shown = self.isVisible()
        self.editable = value
        self.setWindowFlags(surface(value))
        if shown:
            self.show()

    def place(self, x, y):
        self.move(int(x), int(y))

    DEFAULT_RIGHT_GAP = 28 / 1920
    DEFAULT_TOP = 366 / 1080

    def place_default(self, rect):
        left, top, width, height = rect
        self.place(
            left + width - self.width() - round(width * self.DEFAULT_RIGHT_GAP),
            top + round(height * self.DEFAULT_TOP),
        )

    def constrain(self, geometry):
        self.move(
            max(geometry.left(), min(self.x(), geometry.right() - self.width() + 1)),
            max(geometry.top(), min(self.y(), geometry.bottom() - self.height() + 1)),
        )

    def render(self, remaining, preview=False):
        self.remaining, self.preview = remaining, preview
        key = (
            f"{max(0, remaining):04.1f}",
            max(0, min(38, math.ceil(remaining))),
            urgency(remaining) if remaining <= 5 else None,
            preview,
            self.config["accent"],
            self.config["theme"],
        )
        if key != self.drawn_key or self.animating():
            self.drawn_key = key
            self.update()

    def animating(self):
        if not self.config["animations"]:
            return False
        from .themes import theme

        if theme(self.config).motif == "spectrum" and self.remaining > 5:
            return True
        return bool(self.config.get("effects")) and time.perf_counter() - self.appeared < 0.2

    def setWindowOpacity(self, level):
        self.opacity_level = level
        if not self.paint_pending:
            super().setWindowOpacity(level)

    def show(self):
        if not self.isVisible():
            self.appeared = time.perf_counter()
            self.paint_pending = True
            super().setWindowOpacity(0.0)
        super().show()

    def showEvent(self, event):
        native_no_activate(self, not self.editable)
        super().showEvent(event)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        scale = self.config["overlay_scale"]
        p.scale(scale, scale)
        w = self.width() / scale
        from .themes import theme

        spec = theme(self.config)
        accent = QColor(urgency(self.remaining) if self.remaining <= 5 else self.config["accent"])
        if spec.motif == "spectrum" and self.remaining > 5 and self.config["animations"]:
            accent = QColor.fromHsvF((time.perf_counter() / 9) % 1, 0.55, 1)
        path = QPainterPath(QPointF(1, 12))
        for x, y in [(12, 1), (w - 16, 1), (w - 1, 16), (w - 1, 74), (w - 12, 85), (1, 85)]:
            path.lineTo(x, y)
        path.closeSubpath()
        background = QColor(spec.background)
        background.setAlpha(238)
        p.fillPath(path, background)
        if self.config.get("effects"):
            if self.config["animations"]:
                p.setOpacity(min(1, (time.perf_counter() - self.appeared) / 0.18))
            p.setPen(QPen(QColor(spec.secondary), 0.6))
            if spec.motif == "precision":
                for i in range(9):
                    p.drawLine(165 + i * 8, 9, 165 + i * 8, 13 if i % 2 else 17)
            elif spec.motif == "chemical":
                p.drawPolyline(
                    [QPointF(w - 45, 14), QPointF(w - 30, 7), QPointF(w - 16, 14), QPointF(w - 16, 29)]
                )
            elif spec.motif == "electric":
                p.drawPolyline(
                    [QPointF(w - 60, 8), QPointF(w - 46, 8), QPointF(w - 51, 17), QPointF(w - 34, 17)]
                )
            elif spec.motif == "orb":
                p.drawEllipse(QPointF(w - 28, 17), 10, 10)
            p.setOpacity(1)
        p.setPen(QPen(QColor(71, 87, 98, 200), 1))
        p.drawPath(path)
        p.fillRect(QRectF(1, 20, 3, 43), accent)
        p.setFont(self.fonts[0])
        p.setPen(QColor("#a5b4c2"))
        p.drawText(
            QRectF(18, 9, w - 36, 16),
            Qt.AlignLeft,
            "PREVIEW · TIME TO DEFUSE" if self.preview else "TIME TO DEFUSE",
        )
        p.setPen(accent)
        p.setFont(self.fonts[1])
        p.drawText(QRectF(16, 24, 140, 42), Qt.AlignLeft | Qt.AlignVCenter, f"{max(0, self.remaining):04.1f}")
        if not self.config["overlay_compact"]:
            p.setFont(self.fonts[2])
            p.setPen(QColor("#e7ecef"))
            p.drawText(QRectF(165, 30, 90, 32), Qt.AlignLeft, "START DEFUSE\nBEFORE 0")
        for i in range(38):
            p.fillRect(
                QRectF(18 + i * (w - 36) / 38, 73, (w - 36) / 38 - 2, 3),
                accent if i < self.remaining else QColor("#29343f"),
            )
        if self.editable:
            p.setPen(QColor("#ffffff"))
            p.setFont(self.fonts[3])
            p.drawText(QRectF(12, 1, w - 24, 12), Qt.AlignRight, "DRAG TO MOVE")
        p.end()
        if self.paint_pending:
            self.paint_pending = False
            super().setWindowOpacity(self.opacity_level)
            if self.on_painted:
                self.on_painted()

    def mousePressEvent(self, event):
        if self.editable and event.button() == Qt.LeftButton:
            self.drag = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        if self.drag is not None:
            self.move(event.globalPosition().toPoint() - self.drag)

    def mouseReleaseEvent(self, event):
        if self.drag is not None:
            screen = QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
            self.constrain(screen.availableGeometry())
            if self.on_moved:
                self.on_moved(self.x(), self.y())
        self.drag = None


class EdgeStrip(QWidget):
    def __init__(self, config, side):
        super().__init__(None, surface())
        self.setWindowTitle("Spike AI · Perimeter " + side)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.config, self.side = config, side
        self.alpha = 1
        self.look = None

    def showEvent(self, event):
        native_no_activate(self)
        super().showEvent(event)

    def profile(self, start, end, strength):
        g = QLinearGradient(start, end)
        c = QColor(self.config["edge_color"])
        c.setAlphaF(strength)
        g.setColorAt(0, c)
        body = QColor(c)
        body.setAlphaF(strength * 0.6)
        g.setColorAt(0.3, body)
        soft = QColor(c)
        soft.setAlphaF(strength * 0.18)
        g.setColorAt(0.7, soft)
        c.setAlpha(0)
        g.setColorAt(1, c)
        return g

    def paintEvent(self, event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        horizontal = self.side in ("top", "bottom")
        t = h if horizontal else w
        strength = edge_strength(self.config) * self.alpha
        a, b = {
            "top": ((0, 0), (0, h)),
            "bottom": ((0, h), (0, 0)),
            "left": ((0, 0), (w, 0)),
            "right": ((w, 0), (0, 0)),
        }[self.side]
        p.fillRect(self.rect(), self.profile(QPointF(*a), QPointF(*b), strength))
        rim = QColor(self.config["edge_color"]).lighter(125)
        rim.setAlphaF(min(1.0, strength * 1.3))
        thickness = 3
        p.fillRect(
            {
                "top": QRectF(0, 0, w, thickness),
                "bottom": QRectF(0, h - thickness, w, thickness),
                "left": QRectF(0, 0, thickness, h),
                "right": QRectF(w - thickness, 0, thickness, h),
            }[self.side],
            rim,
        )
        if horizontal:
            for x0, x1 in ((0, t), (w, w - t)):
                square = QRectF(min(x0, x1), 0, t, h)
                p.fillRect(square, self.profile(QPointF(x0, 0), QPointF(x1, 0), strength))
                p.fillRect(QRectF(0 if x0 == 0 else w - thickness, 0, thickness, h), rim)
            corners = [QPointF(x, 0 if self.side == "top" else h) for x in (0, w)]
        else:
            x = 0 if self.side == "left" else w
            corners = [QPointF(x, -t), QPointF(x, h + t)]
        for center in corners:
            corner = QRadialGradient(center, t)
            glow = QColor(self.config["edge_color"])
            glow.setAlphaF(strength * 0.45)
            corner.setColorAt(0, glow)
            glow.setAlpha(0)
            corner.setColorAt(1, glow)
            p.fillRect(self.rect(), corner)
        p.end()


class EdgeAlert:
    def __init__(self, config):
        self.config = config
        self.strips = {side: EdgeStrip(config, side) for side in ("top", "bottom", "left", "right")}
        self.visible = False
        self.geometry = None
        self.start = 0

    def position(self, rect):
        x, y, w, h = rect
        t = min(self.config["edge_thickness"], max(8, min(w, h) // 8))
        geometries = {
            "top": (x, y, w, t),
            "bottom": (x, y + h - t, w, t),
            "left": (x, y + t, t, h - 2 * t),
            "right": (x + w - t, y + t, t, h - 2 * t),
        }
        for side, geo in geometries.items():
            self.strips[side].setGeometry(*map(int, geo))
        self.geometry = rect

    def render(self, remaining, focused, rect, preview=False, t=None):
        if not edge_due(remaining, focused, self.config, preview):
            self.hide()
            return
        t = time.perf_counter() if t is None else t
        if not self.visible:
            self.start = t
        self.position(rect)
        moving = self.config["animations"] and self.config["edge_animations"]
        pulse = 0.675 + 0.325 * math.sin(2 * math.pi * t * self.config["edge_speed"]) if moving else 1
        fade = min(1, max(0, (t - self.start) / 0.25)) if moving else 1
        for strip in self.strips.values():
            look = (self.config["edge_color"], edge_strength(self.config), strip.size().toTuple())
            if strip.alpha != 1 or strip.look != look:
                strip.alpha, strip.look = 1, look
                strip.update()
            strip.setWindowOpacity(pulse * fade)
            strip.show()
        self.visible = True

    def hide(self):
        for strip in self.strips.values():
            strip.hide()
        self.visible = False

    def close(self):
        for strip in self.strips.values():
            strip.close()
