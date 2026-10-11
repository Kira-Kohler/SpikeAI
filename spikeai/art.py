import math
import time
from collections import OrderedDict
from pathlib import Path
from PySide6.QtCore import Qt, QRect, QRectF, QPointF
from PySide6.QtGui import (
    QColor,
    QPainter,
    QFont,
    QFontMetricsF,
    QPixmap,
    QLinearGradient,
    QRadialGradient,
    QPen,
    QPainterPath,
    QImage,
    QBrush,
    QRegion,
)
from PySide6.QtWidgets import QWidget
from .resources import resource_path
from .widgets import flowing
from .themes import THEMES, theme


class ScaledArt:
    def __init__(self, limit=6):
        self.limit = limit
        self.items = OrderedDict()

    def get(self, key, pix, dest, source, dpr=1.0):
        key = (key, pix.cacheKey(), dest.x(), dest.y(), dest.width(), dest.height(), source.x(), source.y(),
               source.width(), source.height(), dpr)
        item = self.items.get(key)
        if item is None:
            left, top = math.floor(dest.x()), math.floor(dest.y())
            width, height = math.ceil(dest.right()) - left, math.ceil(dest.bottom()) - top
            image = QPixmap(max(1, round(width * dpr)), max(1, round(height * dpr)))
            image.setDevicePixelRatio(dpr)
            image.fill(Qt.transparent)
            q = QPainter(image)
            q.setRenderHint(QPainter.Antialiasing)
            q.setRenderHint(QPainter.SmoothPixmapTransform)
            q.drawPixmap(dest.translated(-left, -top), pix, source)
            q.end()
            item = (QPointF(left, top), image)
            self.items[key] = item
            if len(self.items) > self.limit:
                self.items.popitem(last=False)
        else:
            self.items.move_to_end(key)
        return item

    def draw(self, p, key, pix, dest, source):
        origin, image = self.get(key, pix, dest, source, p.device().devicePixelRatioF())
        p.drawPixmap(origin, image)


_GLOWS = OrderedDict()


def paint_glow(p, rect, color):
    w, h = rect.width(), rect.height()
    radial = QRadialGradient(QPointF(rect.x() + w * 0.69, rect.y() + h * 0.5), w * 0.65)
    radial.setColorAt(0, color)
    clear = QColor(color)
    clear.setAlpha(0)
    radial.setColorAt(1, clear)
    if rect.x() != int(rect.x()) or rect.y() != int(rect.y()):
        p.fillRect(rect, radial)
        return
    dpr = p.device().devicePixelRatioF()
    key = (w, h, color.rgba(), dpr)
    glow = _GLOWS.get(key)
    if glow is None:
        glow = QPixmap(max(1, round(w * dpr)), max(1, round(h * dpr)))
        glow.setDevicePixelRatio(dpr)
        glow.fill(Qt.transparent)
        radial.setCenter(QPointF(w * 0.69, h * 0.5))
        radial.setFocalPoint(QPointF(w * 0.69, h * 0.5))
        q = QPainter(glow)
        q.fillRect(QRectF(0, 0, w, h), radial)
        q.end()
        _GLOWS[key] = glow
        if len(_GLOWS) > 8:
            _GLOWS.popitem(last=False)
    else:
        _GLOWS.move_to_end(key)
    p.drawPixmap(rect.topLeft(), glow)


def motif_glow(p, rect, spec, phase, strength):
    primary = QColor.fromHsvF((phase / 9) % 1, 0.6, 1) if spec.motif == "spectrum" else QColor(spec.accent)
    glow = QColor(primary)
    glow.setAlpha(round(65 * strength))
    if spec.motif == "spectrum":
        w, h = rect.width(), rect.height()
        radial = QRadialGradient(QPointF(rect.x() + w * 0.69, rect.y() + h * 0.5), w * 0.65)
        radial.setColorAt(0, glow)
        glow.setAlpha(0)
        radial.setColorAt(1, glow)
        p.fillRect(rect, radial)
    else:
        paint_glow(p, rect, glow)


def paint_motif(p, rect, spec, phase, strength=1, glow=True):
    p.save()
    p.setOpacity(strength)
    p.setClipRect(rect)
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    cx, cy = x + w * 0.69, y + h * 0.5
    primary, secondary = QColor(spec.accent), QColor(spec.secondary)
    if spec.motif == "spectrum":
        primary = QColor.fromHsvF((phase / 9) % 1, 0.6, 1)
    if glow:
        motif_glow(p, rect, spec, phase, strength)
    p.setBrush(Qt.NoBrush)
    if spec.motif == "fire":
        for i in range(7):
            base = x + w * (0.40 + i * 0.06)
            path = QPainterPath(QPointF(base, y + h))
            path.cubicTo(
                base - w * 0.07,
                y + h * 0.6,
                base + w * 0.10,
                y + h * 0.43,
                base + w * 0.02,
                y + h * (0.16 + 0.08 * math.sin(i + phase)),
            )
            path.cubicTo(base + w * 0.17, y + h * 0.55, base + w * 0.06, y + h * 0.8, base + w * 0.13, y + h)
            c = QColor(primary if i % 2 else secondary)
            c.setAlpha(20 + i * 3)
            p.fillPath(path, c)
        for i in range(16):
            a = (i * 0.619) % 1
            b = (phase * 0.10 + i * 0.13) % 1
            c = QColor(secondary)
            c.setAlpha(round(130 * (1 - b)))
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawEllipse(QPointF(x + w * (0.43 + a * 0.55), y + h * (1 - b)), 1.2, 2.0)
    elif spec.motif == "orb":
        for i in range(5):
            r = h * (0.18 + i * 0.09) + 5 * math.sin(phase * 1.5 + i)
            c = QColor(primary)
            c.setAlpha(110 - i * 18)
            p.setPen(QPen(c, 1.3))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r * 0.76, r)
        for i in range(8):
            a = phase * 0.3 + i * math.pi / 4
            p.setBrush(secondary)
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(cx + math.cos(a) * h * 0.37, cy + math.sin(a) * h * 0.37), 2, 2)
    elif spec.motif == "chemical":
        for i in range(9):
            xx = x + w * (0.45 + (i % 3) * 0.16)
            yy = y + h * (0.2 + (i // 3) * 0.29)
            path = QPainterPath()
            for j in range(7):
                a = j * math.pi / 3
                pt = QPointF(xx + math.cos(a) * h * 0.13, yy + math.sin(a) * h * 0.13)
                path.moveTo(pt) if j == 0 else path.lineTo(pt)
            c = QColor(primary)
            c.setAlpha(45 + round(22 * math.sin(phase + i)))
            p.setPen(QPen(c, 1))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        for i in range(3):
            fog = QRadialGradient(
                QPointF(x + w * (0.45 + i * 0.17), y + h * (0.68 + 0.1 * math.sin(phase * 0.4 + i))), h * 0.5
            )
            c = QColor(primary)
            c.setAlpha(25)
            fog.setColorAt(0, c)
            c.setAlpha(0)
            fog.setColorAt(1, c)
            p.fillRect(rect, fog)
    elif spec.motif == "electric":
        for i in range(6):
            yy = y + h * (0.13 + i * 0.15)
            path = QPainterPath(QPointF(x + w * 0.42, yy))
            for j in range(8):
                path.lineTo(x + w * (0.42 + j * 0.085), yy + math.sin(j * 2 + i + phase * 3) * h * 0.04)
            c = QColor(primary if i % 2 else secondary)
            c.setAlpha(110 if i == int(phase * 2) % 6 else 38)
            p.setPen(QPen(c, 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
    elif spec.motif == "precision":
        for r in (h * 0.25, h * 0.4, h * 0.53):
            c = QColor(primary)
            c.setAlpha(60)
            p.setPen(QPen(c, 0.8))
            p.drawEllipse(QPointF(cx, cy), r, r)
        for i in range(60):
            a = i * math.pi / 30
            r = h * 0.4
            p.setPen(QPen(secondary if i % 5 == 0 else primary, 1))
            p.drawLine(
                QPointF(cx + math.cos(a) * r, cy + math.sin(a) * r),
                QPointF(
                    cx + math.cos(a) * (r - (9 if i % 5 == 0 else 4)),
                    cy + math.sin(a) * (r - (9 if i % 5 == 0 else 4)),
                ),
            )
        p.setPen(QPen(secondary, 1.4))
        a = phase * 0.12
        p.drawLine(QPointF(cx, cy), QPointF(cx + math.cos(a) * h * 0.24, cy + math.sin(a) * h * 0.24))
        p.setPen(QPen(primary, 1))
        p.drawLine(QPointF(x + w * 0.4, y + h * 0.1), QPointF(x + w * 0.95, y + h * 0.1))
        shine = QLinearGradient(x + w * (phase * 0.05 % 1), y, x + w * (phase * 0.05 % 1) + 60, y)
        c = QColor(secondary)
        c.setAlpha(0)
        shine.setColorAt(0, c)
        shine.setColorAt(1, c)
        c.setAlpha(50)
        shine.setColorAt(0.5, c)
        p.fillRect(rect, shine)
    elif spec.motif == "butterfly":
        for i in range(3):
            smoke = QRadialGradient(
                QPointF(x + w * (0.5 + i * 0.16), y + h * (0.75 - 0.08 * math.sin(phase * 0.3 + i * 2))), h * 0.55
            )
            c = QColor(primary if i != 1 else secondary)
            c.setAlpha(30)
            smoke.setColorAt(0, c)
            c.setAlpha(0)
            smoke.setColorAt(1, c)
            p.fillRect(rect, smoke)
        p.setPen(Qt.NoPen)
        for i in range(9):
            drift = (phase * 0.035 + i * 0.137) % 1
            bx = x + w * (0.44 + ((i * 0.381) % 1) * 0.5) + math.sin(phase * 0.7 + i) * 8
            by = y + h * (1.05 - drift * 1.1)
            size = h * (0.035 + 0.02 * ((i * 0.53) % 1))
            flap = 0.35 + 0.65 * abs(math.sin(phase * 3 + i * 1.7))
            c = QColor(primary if i % 3 else secondary)
            c.setAlpha(round(150 * math.sin(math.pi * drift)))
            p.setBrush(c)
            for side in (-1, 1):
                p.drawEllipse(QPointF(bx + side * size * 0.55 * flap, by - size * 0.25), size * 0.6 * flap, size * 0.75)
                p.drawEllipse(QPointF(bx + side * size * 0.4 * flap, by + size * 0.45), size * 0.4 * flap, size * 0.45)
    elif spec.motif == "spectrum":
        for i in range(5):
            color = QColor.fromHsvF((phase / 9 + i * 0.14) % 1, 0.55, 1)
            color.setAlpha(120)
            p.setPen(QPen(color, 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(
                QRectF(x + w * 0.43 + i * 9, y + 14 + i * 9, w * 0.5 - i * 18, h - 28 - i * 18), 14, 14
            )
    else:
        for i in range(6):
            c = QColor(primary)
            c.setAlpha(18 + i * 4)
            p.setPen(QPen(c, 1))
            p.drawLine(QPointF(x + w * 0.48 + i * 22, y), QPointF(x + w * 0.76 + i * 22, y + h))
    p.restore()


class Hero(QWidget):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.setFixedHeight(244)
        self.pixmaps = {
            p.stem: QPixmap(str(p)) for p in sorted(Path(resource_path("assets", "art")).glob("*.jpg"))
        }
        self.shadow_pixmap = QPixmap()
        if "omen" in self.pixmaps:
            self.shadow_pixmap = QPixmap.fromImage(
                self.pixmaps["omen"].toImage().convertToFormat(QImage.Format_Grayscale8)
            )
        self.last_theme = config["theme"]
        self.previous_theme = None
        self.theme_started = 0.0
        self.remaining = None
        self.phase = 0.0
        self.cycle = 0
        self.previous_agent = None
        self.fade_started = 0.0
        self.last_cycle = time.perf_counter()
        self.hovered = False
        self.paused_at = None
        self.art = ScaledArt()
        self.layer = None
        self.fonts = {
            "small": QFont("Bahnschrift", 9),
            "title": QFont("Bahnschrift", 27),
            "number": QFont("Bahnschrift", 37),
            "label": QFont("Bahnschrift", 11),
            "note": QFont("Segoe UI", 8),
            "agent": QFont("Bahnschrift", 10),
        }
        self.setAccessibleName("Spike AI session timer")

    @property
    def agent(self):
        spec = theme(self.config)
        if spec.agent:
            return spec.agent
        if self.config["theme"] == "Obsidian":
            return "omen"
        keys = list(self.pixmaps) or [t.agent for t in THEMES.values() if t.agent]
        return keys[self.cycle % len(keys)] if keys else ""

    def transition_theme(self):
        self.previous_theme = THEMES.get(self.last_theme)
        self.last_theme = self.config["theme"]
        self.theme_started = time.perf_counter()
        self.previous_agent = None

    def pause(self):
        if self.paused_at is None:
            self.paused_at = time.perf_counter()

    def resume(self):
        if self.paused_at is None:
            return
        start, self.paused_at = self.paused_at, None
        paused = time.perf_counter() - start
        for name in ("last_cycle", "fade_started", "theme_started"):
            if getattr(self, name) <= start:
                setattr(self, name, getattr(self, name) + paused)

    def transitioning(self):
        now = time.perf_counter()
        return bool(self.config.get("animations")) and (
            now - self.fade_started < 0.55 or now - self.theme_started < 0.26
        )

    def animated_region(self):
        w, h = self.width(), self.height()
        region = QRegion(QRect(math.floor(w * 0.31) - 1, 0, w - math.floor(w * 0.31) + 1, h))
        if theme(self.config).motif == "spectrum" or self.transitioning():
            region = QRegion(self.rect())
        return region

    def advance(self):
        self.resume()
        now = time.perf_counter()
        if self.config.get("animations"):
            self.phase = now
            if self.config["theme"] == "RGB" and not self.hovered and now - self.last_cycle >= 3:
                self.previous_agent = self.agent
                self.cycle += 1
                self.fade_started = now
                self.last_cycle = now
        self.update(self.animated_region())

    def enterEvent(self, event):
        self.hovered = True
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered = False
        self.last_cycle = time.perf_counter()
        super().leaveEvent(event)

    def draw_agent(self, p, agent, opacity):
        pix = self.pixmaps.get(agent)
        if not pix:
            if self.config["theme"] == "RGB":
                spec = next((t for t in THEMES.values() if t.agent == agent), theme(self.config))
                p.save()
                p.setOpacity(opacity)
                paint_motif(
                    p, QRectF(self.rect()), spec, self.phase, self.config.get("animation_intensity", 0.7)
                )
                p.restore()
            return
        if self.config["theme"] == "Obsidian" and not self.shadow_pixmap.isNull():
            pix = self.shadow_pixmap
        p.save()
        p.setOpacity(opacity)
        dest = QRectF(self.width() * 0.4, 0, self.width() * 0.6, self.height())
        ratio = max(dest.width() / pix.width(), dest.height() / pix.height())
        source = QRectF(
            (pix.width() - dest.width() / ratio) * 0.5,
            (pix.height() - dest.height() / ratio) * 0.5,
            dest.width() / ratio,
            dest.height() / ratio,
        )
        self.art.draw(p, agent, pix, dest, source)
        p.restore()

    LAYER_LEFT = 0.29

    def motif_layer(self, p, spec):
        dpr = p.device().devicePixelRatioF()
        left = math.floor(self.width() * self.LAYER_LEFT)
        size = (max(1, round((self.width() - left) * dpr)), max(1, round(self.height() * dpr)))
        if self.layer is None or (self.layer.width(), self.layer.height()) != size:
            self.layer = QImage(*size, QImage.Format_ARGB32_Premultiplied)
            self.layer.setDevicePixelRatio(dpr)
        self.layer.fill(Qt.transparent)
        q = QPainter(self.layer)
        q.setRenderHint(QPainter.Antialiasing)
        q.translate(-left, 0)
        paint_motif(q, QRectF(self.rect()), spec, self.phase, 1, glow=False)
        q.end()
        return QPointF(left, 0), self.layer

    def composite_motif(self, p, spec, layer, strength):
        if strength <= 0 or layer is None:
            return
        rect = QRectF(self.rect())
        p.save()
        p.setOpacity(strength)
        p.setClipRect(rect)
        motif_glow(p, rect, spec, self.phase, strength)
        p.drawImage(*layer)
        p.restore()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        spec = theme(self.config)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(spec.surface))
        strength = self.config.get("animation_intensity", 0.7) if self.config.get("effects") else 0
        progress = (
            min(1, (time.perf_counter() - self.theme_started) / 0.26) if self.config.get("animations") else 1
        )
        if self.previous_theme and progress < 1:
            p.save()
            p.setOpacity(1 - progress)
            paint_motif(p, QRectF(self.rect()), self.previous_theme, self.phase, strength * (1 - progress))
            self.draw_agent(p, self.previous_theme.agent, 1 - progress)
            p.restore()
        layer = self.motif_layer(p, spec) if strength * progress > 0 else None
        self.composite_motif(p, spec, layer, strength * progress)
        f = min(1, (time.perf_counter() - self.fade_started) / 0.55) if self.config.get("animations") else 1
        if self.previous_agent and f < 1:
            self.draw_agent(p, self.previous_agent, 1 - f)
        self.draw_agent(p, self.agent, f * progress)
        self.composite_motif(p, spec, layer, strength * 0.24 * progress)
        gradient = QLinearGradient(0, 0, w, 0)
        gradient.setColorAt(0, QColor(spec.surface))
        gradient.setColorAt(0.31, QColor(spec.surface))
        c = QColor(spec.surface)
        c.setAlpha(0)
        gradient.setColorAt(0.82, c)
        p.fillRect(self.rect(), gradient)
        spectrum = spec.motif == "spectrum"

        def tint(color, x1, x2, width=1.0):
            return QPen(QBrush(flowing(x1, 0, x2, 0)), width) if spectrum else QPen(QColor(color), width)

        fonts = self.fonts
        p.setPen(tint(spec.accent, 24, 140))
        p.setFont(fonts["small"])
        p.drawText(24, 32, spec.title)
        p.setPen(QColor("#f4f1ed"))
        p.setFont(fonts["title"])
        p.drawText(24, 83, "EVERY SECOND")
        p.drawText(24, 122, "COUNTS.")
        p.setPen(tint(spec.secondary, 26, 210))
        p.setFont(fonts["small"])
        p.drawText(26, 148, spec.slogan)
        number = f"{self.remaining:04.1f}" if self.remaining is not None else "38.0"
        p.setFont(fonts["number"])
        p.setPen(QColor("#f4f1ed"))
        p.drawText(23, 207, number)
        x = 23 + QFontMetricsF(p.font()).horizontalAdvance("38.0") + 18
        p.setFont(fonts["label"])
        p.setPen(tint(spec.accent, x, x + 120))
        p.drawText(QPointF(x, 187), "TIME TO DEFUSE")
        p.setFont(fonts["note"])
        p.setPen(QColor("#aab7c7"))
        p.drawText(QPointF(x, 205), "Start before 0 · not the explosion")
        if self.pixmaps:
            p.setFont(fonts["agent"])
            p.setPen(tint(spec.secondary, w * 0.84, w * 0.96))
            p.drawText(
                QRectF(w * 0.5, h - 43, w * 0.46, 23),
                Qt.AlignRight,
                self.agent.upper().replace("KAY-O", "KAY/O"),
            )
        p.setPen(tint(spec.accent, 24, w - 24, 2))
        p.drawLine(
            24,
            h - 14,
            round(24 + (w - 48) * ((self.remaining or 0) / 38 if self.remaining is not None else 1)),
            h - 14,
        )
        p.end()
