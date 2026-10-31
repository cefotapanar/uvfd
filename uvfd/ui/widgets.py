# -*- coding: utf-8 -*-
"""Hand-painted widgets: gauge, KPI tile, trend chart, LEDs, status pill."""

from __future__ import annotations

import math
import time
from collections import deque

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QFontMetricsF, QLinearGradient,
                           QPainter, QPainterPath, QPen, QRadialGradient)
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from . import theme as th


class Card(QFrame):
    """Rounded surface with a small caps title and an optional header widget."""

    def __init__(self, title: str = "", parent=None, pad: int = 16):
        super().__init__(parent)
        self.setObjectName("Card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(pad, pad - 2, pad, pad)
        self.lay.setSpacing(10)
        self.head = QHBoxLayout()
        self.head.setSpacing(8)
        self.title = QLabel(title.upper())
        self.title.setObjectName("CardTitle")
        self.head.addWidget(self.title)
        self.head.addStretch(1)
        if title:
            self.lay.addLayout(self.head)

    def set_title(self, text: str):
        self.title.setText(text.upper())


def hline() -> QFrame:
    f = QFrame()
    f.setFixedHeight(1)
    f.setStyleSheet("background:%s;" % th.BORDER_SOFT)
    return f


def vsep() -> QFrame:
    f = QFrame()
    f.setObjectName("Sep")
    f.setFixedWidth(1)
    return f


# ============================================================ gauge

class Gauge(QWidget):
    """270° arc: running frequency, with a setpoint marker."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.value = 0.0
        self.shown = 0.0
        self.setpoint = None
        self.maximum = 50.0
        self.unit = "Hz"
        self.caption = ""
        self.sub = ""
        self.active = False
        self.fault = False
        self.setMinimumSize(250, 230)
        self._anim = QTimer(self)
        self._anim.timeout.connect(self._step)
        self._anim.start(16)

    def sizeHint(self):
        return QSize(300, 270)

    def set_value(self, v, setpoint=None, maximum=None):
        self.value = 0.0 if v is None else float(v)
        self.setpoint = setpoint
        if maximum:
            self.maximum = float(maximum)

    def _step(self):
        d = self.value - self.shown
        if abs(d) < 0.005:
            if self.shown != self.value:
                self.shown = self.value
                self.update()
            return
        self.shown += d * 0.22
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        side = min(w, h * 1.08)
        r = side / 2 - 14
        cx, cy = w / 2, h / 2 + side * 0.05
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        start, span = 225.0, -270.0
        thick = max(10.0, r * 0.085)

        # ticks
        p.setPen(QPen(th.qc(th.FAINT), 1.2))
        for k in range(0, 51):
            a = math.radians(start + span * k / 50)
            long_ = k % 10 == 0
            r1 = r + thick / 2 + 5
            r2 = r1 + (7 if long_ else 3)
            p.setPen(QPen(th.qc(th.MUTED if long_ else th.FAINT), 1.4 if long_ else 1))
            p.drawLine(QPointF(cx + r1 * math.cos(a), cy - r1 * math.sin(a)),
                       QPointF(cx + r2 * math.cos(a), cy - r2 * math.sin(a)))

        # track
        pen = QPen(th.qc(th.RAISED), thick, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, int(start * 16), int(span * 16))

        frac = max(0.0, min(1.0, self.shown / self.maximum)) if self.maximum else 0
        if frac > 0.001:
            grad = QConicalGradient(cx, cy, start)
            col = th.RED if self.fault else th.ACCENT
            grad.setColorAt(0.0, th.qc(col))
            grad.setColorAt(0.75, th.qc("#1F8F80" if not self.fault else "#B53A4C"))
            grad.setColorAt(1.0, th.qc(col))
            pen = QPen(QBrush(th.qc(col)), thick, Qt.SolidLine, Qt.RoundCap)
            # soft glow
            glow = QPen(th.qc(col, 46), thick + 10, Qt.SolidLine, Qt.RoundCap)
            p.setPen(glow)
            p.drawArc(rect, int(start * 16), int(span * frac * 16))
            p.setPen(pen)
            p.drawArc(rect, int(start * 16), int(span * frac * 16))

        # setpoint marker
        if self.setpoint is not None and self.maximum:
            sf = max(0.0, min(1.0, self.setpoint / self.maximum))
            a = math.radians(start + span * sf)
            r1, r2 = r - thick / 2 - 4, r + thick / 2 + 4
            p.setPen(QPen(th.qc(th.BLUE), 3, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(cx + r1 * math.cos(a), cy - r1 * math.sin(a)),
                       QPointF(cx + r2 * math.cos(a), cy - r2 * math.sin(a)))

        # value text
        txt = "%.2f" % self.shown
        f = th.font(max(20, r * 0.30), 600, display=True, tabular=True)
        p.setFont(f)
        p.setPen(th.qc(th.TEXT if not self.fault else th.RED))
        fm = QFontMetricsF(f)
        tw = fm.horizontalAdvance(txt)
        p.drawText(QPointF(cx - tw / 2, cy + fm.capHeight() * 0.42), txt)
        fu = th.font(max(9, r * 0.085), 600)
        p.setFont(fu)
        p.setPen(th.qc(th.MUTED))
        fmu = QFontMetricsF(fu)
        p.drawText(QPointF(cx - fmu.horizontalAdvance(self.unit) / 2, cy + fm.capHeight() * 0.42 + fmu.height() + 4), self.unit)
        if self.sub:
            fs = th.font(max(8.5, r * 0.07), 500)
            p.setFont(fs)
            p.setPen(th.qc(th.BLUE))
            fms = QFontMetricsF(fs)
            p.drawText(QPointF(cx - fms.horizontalAdvance(self.sub) / 2, cy + r * 0.62), self.sub)
        # scale labels 0 and max
        fl = th.font(8, 500, tabular=True)
        p.setFont(fl)
        p.setPen(th.qc(th.FAINT))
        for k, val in ((0, 0), (1, self.maximum)):
            a = math.radians(start + span * k)
            rr = r + thick / 2 + 4
            s = "%g" % round(val, 1)
            x = cx + rr * math.cos(a) - (QFontMetricsF(fl).horizontalAdvance(s) / 2)
            y = cy - rr * math.sin(a) + 18
            p.drawText(QPointF(x, y), s)
        p.end()


# ============================================================ sparkline + KPI tile

class Sparkline(QWidget):
    """Last `window` seconds, drawn against time and from a zero baseline, so a
    value that just appeared is a short line on the right, not a sliver."""

    def __init__(self, color=th.ACCENT, window: float = 60.0, parent=None):
        super().__init__(parent)
        self.color = color
        self.window = window
        self.data = deque(maxlen=600)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(28)

    def push(self, v):
        if v is not None:
            self.data.append((time.time(), float(v)))
            self.update()

    def clear(self):
        self.data.clear()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height() - 2
        p.setPen(QPen(th.qc(th.BORDER), 1))
        p.drawLine(QPointF(0, h + 0.5), QPointF(w, h + 0.5))
        now = time.time()
        pts_v = [(t, v) for t, v in self.data if t >= now - self.window]
        if len(pts_v) < 2:
            p.end()
            return
        vals = [v for _, v in pts_v]
        lo, hi = min(min(vals), 0.0), max(vals)
        if hi - lo < 1e-9:
            hi = lo + 1
        hi += (hi - lo) * 0.08
        pts = [QPointF(w * (1 - (now - t) / self.window), h - (v - lo) / (hi - lo) * (h - 3)) for t, v in pts_v]
        if pts[0].x() > 6:
            p.setPen(QPen(th.qc(self.color, 90), 1.2, Qt.DotLine))
            p.drawLine(QPointF(0, pts[0].y()), pts[0])
        path = QPainterPath(pts[0])
        for pt in pts[1:]:
            path.lineTo(pt)
        fill = QPainterPath(path)
        fill.lineTo(pts[-1].x(), h)
        fill.lineTo(pts[0].x(), h)
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, th.qc(self.color, 80))
        g.setColorAt(1, th.qc(self.color, 0))
        p.fillPath(fill, g)
        p.setPen(QPen(th.qc(self.color), 1.7))
        p.drawPath(path)
        p.setBrush(th.qc(self.color))
        p.setPen(Qt.NoPen)
        p.drawEllipse(pts[-1], 2.8, 2.8)
        p.end()


class KpiTile(QFrame):
    def __init__(self, title: str, unit: str, color=th.ACCENT, dec: int = 1, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.dec = dec
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        self.lbl = QLabel(title.upper())
        self.lbl.setObjectName("CardTitle")
        lay.addWidget(self.lbl)
        row = QHBoxLayout()
        row.setSpacing(5)
        self.val = QLabel("—")
        self.val.setFont(th.font(20, 600, display=True, tabular=True))
        self.unit = QLabel(unit)
        self.unit.setObjectName("Muted")
        self.unit.setFont(th.font(10, 600))
        row.addWidget(self.val, 0, Qt.AlignBaseline)
        row.addWidget(self.unit, 0, Qt.AlignBaseline)
        row.addStretch(1)
        lay.addLayout(row)
        self.minmax = QLabel(" ")
        self.minmax.setFont(th.font(8, 600, tabular=True))
        self.minmax.setStyleSheet("color:%s;" % th.MUTED)
        lay.addWidget(self.minmax)
        self.spark = Sparkline(color)
        lay.addWidget(self.spark)
        self.lo = self.hi = None

    def set_title(self, t: str):
        self.lbl.setText(t.upper())

    def set_value(self, v, text: str | None = None):
        if v is None:
            self.val.setText("—")
            return
        self.val.setText(text if text is not None else ("%.*f" % (self.dec, v)))
        self.spark.push(v)
        self.lo = v if self.lo is None else min(self.lo, v)
        self.hi = v if self.hi is None else max(self.hi, v)
        self.minmax.setText("▲ %.*f    ▼ %.*f" % (self.dec, self.hi, self.dec, self.lo))

    def reset(self):
        self.lo = self.hi = None
        self.val.setText("—")
        self.minmax.setText(" ")
        self.spark.clear()


# ============================================================ trend chart

class TrendChart(QWidget):
    """Up to four series over a sliding time window, each on its own scale."""

    def __init__(self, window_s: float = 120.0, parent=None):
        super().__init__(parent)
        self.window = window_s
        self.series: list[dict] = []
        self.setMinimumHeight(120)

    def add_series(self, key: str, label: str, unit: str, color: str):
        self.series.append({"key": key, "label": label, "unit": unit, "color": color,
                            "pts": deque(maxlen=4000)})

    def set_label(self, key: str, label: str):
        for s in self.series:
            if s["key"] == key:
                s["label"] = label

    def push(self, key: str, t: float, v):
        if v is None:
            return
        for s in self.series:
            if s["key"] == key:
                s["pts"].append((t, float(v)))

    def clear(self):
        for s in self.series:
            s["pts"].clear()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        left, right, top, bottom = 44, 44, 40, 22
        pw, ph = w - left - right, h - top - bottom
        now = time.time()
        t0 = now - self.window
        # legend
        x = left
        p.setFont(th.font(8.5, 600))
        fm = QFontMetricsF(p.font())
        for s in self.series:
            last = s["pts"][-1][1] if s["pts"] else None
            p.setBrush(th.qc(s["color"]))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(x, 8, 10, 10), 3, 3)
            txt = s["label"] + ("  %.2f %s" % (last, s["unit"]) if last is not None else "")
            p.setPen(th.qc(th.MUTED))
            p.drawText(QPointF(x + 15, 17), txt)
            x += 15 + fm.horizontalAdvance(txt) + 18
        # grid
        p.setPen(QPen(th.qc(th.BORDER_SOFT), 1))
        for k in range(5):
            y = top + ph * k / 4
            p.drawLine(QPointF(left, y), QPointF(left + pw, y))
        p.setFont(th.font(7.5, 500, tabular=True))
        p.setPen(th.qc(th.FAINT))
        for k in range(0, int(self.window) + 1, 30):
            xx = left + pw * (1 - k / self.window)
            p.drawText(QPointF(xx - 10, h - 6), ("-%ds" % k) if k else "0")
        # series
        for idx, s in enumerate(self.series):
            pts = [(t, v) for t, v in s["pts"] if t >= t0 - 2]
            if not pts:
                continue
            vals = [v for _, v in pts]
            hi = max(max(vals), 1e-6)
            nice = _nice_max(hi)
            if idx < 2:
                p.setPen(th.qc(s["color"], 200))
                p.setFont(th.font(8, 700))
                if idx == 0:
                    p.drawText(QPointF(6, top - 8), s["unit"])
                else:
                    p.drawText(QPointF(left + pw + 6, top - 8), s["unit"])
                p.setFont(th.font(7.5, 600, tabular=True))
                for k in range(5):
                    y = top + ph * k / 4
                    lab = "%g" % round(nice * (1 - k / 4), 1)
                    if idx == 0:
                        p.drawText(QPointF(6, y + 4), lab)
                    else:
                        p.drawText(QPointF(left + pw + 6, y + 4), lab)
            path = QPainterPath()
            first = True
            for t, v in pts:
                xx = left + pw * (t - t0) / self.window
                yy = top + ph * (1 - v / nice)
                if first:
                    path.moveTo(xx, yy)
                    first = False
                else:
                    path.lineTo(xx, yy)
            if idx == 0:
                fill = QPainterPath(path)
                fill.lineTo(path.currentPosition().x(), top + ph)
                fill.lineTo(left + pw * max(0, (pts[0][0] - t0)) / self.window, top + ph)
                g = QLinearGradient(0, top, 0, top + ph)
                g.setColorAt(0, th.qc(s["color"], 55))
                g.setColorAt(1, th.qc(s["color"], 0))
                p.fillPath(fill, g)
            p.setPen(QPen(th.qc(s["color"]), 2.0 if idx == 0 else 1.6))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        p.end()


def _nice_max(v: float) -> float:
    if v <= 0:
        return 1.0
    e = 10 ** math.floor(math.log10(v))
    for m in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if v <= m * e:
            return m * e
    return 10 * e


# ============================================================ LEDs, bars, pill

class Led(QWidget):
    def __init__(self, label: str, color=th.ACCENT, parent=None):
        super().__init__(parent)
        self.label = label
        self.color = color
        self.on = False
        self.setFixedSize(44, 40)

    def set_on(self, on: bool):
        if on != self.on:
            self.on = on
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(self.width() / 2, 12)
        if self.on:
            g = QRadialGradient(c, 13)
            g.setColorAt(0, th.qc(self.color, 120))
            g.setColorAt(1, th.qc(self.color, 0))
            p.setBrush(g)
            p.setPen(Qt.NoPen)
            p.drawEllipse(c, 13, 13)
            p.setBrush(th.qc(self.color))
        else:
            p.setBrush(th.qc(th.RAISED))
        p.setPen(QPen(th.qc(th.BORDER), 1))
        p.drawEllipse(c, 6.5, 6.5)
        p.setPen(th.qc(th.TEXT if self.on else th.FAINT))
        p.setFont(th.font(7.5, 700))
        fm = QFontMetricsF(p.font())
        p.drawText(QPointF(self.width() / 2 - fm.horizontalAdvance(self.label) / 2, 35), self.label)
        p.end()


class Bar(QWidget):
    """Horizontal level bar: AI inputs."""

    def __init__(self, label: str, maximum: float = 10.0, unit: str = "V", color=th.BLUE, parent=None):
        super().__init__(parent)
        self.label, self.maximum, self.unit, self.color = label, maximum, unit, color
        self.value = None
        self.setFixedHeight(22)

    def set_value(self, v):
        self.value = v
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setFont(th.font(8.5, 600))
        p.setPen(th.qc(th.MUTED))
        p.drawText(QRectF(0, 0, 44, h), Qt.AlignVCenter | Qt.AlignLeft, self.label)
        txt = "—" if self.value is None else "%.2f %s" % (self.value, self.unit)
        p.setFont(th.font(8.5, 600, tabular=True))
        p.setPen(th.qc(th.TEXT))
        p.drawText(QRectF(w - 70, 0, 70, h), Qt.AlignVCenter | Qt.AlignRight, txt)
        bx, bw = 46, w - 46 - 76
        p.setPen(Qt.NoPen)
        p.setBrush(th.qc(th.RAISED))
        p.drawRoundedRect(QRectF(bx, h / 2 - 3, bw, 6), 3, 3)
        if self.value is not None and self.maximum:
            f = max(0.0, min(1.0, abs(self.value) / self.maximum))
            p.setBrush(th.qc(self.color))
            p.drawRoundedRect(QRectF(bx, h / 2 - 3, max(6, bw * f), 6), 3, 3)
        p.end()


class StatusPill(QWidget):
    """Big drive status: pulsing dot + text."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.text = ""
        self.color = th.FAINT
        self.pulse = False
        self.solid = False
        self.phase = 0.0
        self.setFixedHeight(40)
        self._t = QTimer(self)
        self._t.timeout.connect(self._tick)
        self._t.start(40)

    def set_state(self, text: str, color: str, pulse: bool, solid: bool = False):
        self.text, self.color, self.pulse, self.solid = text, color, pulse, solid
        self.update()

    def _tick(self):
        if self.pulse:
            self.phase = (self.phase + 0.06) % (2 * math.pi)
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = QRectF(0.5, 0.5, w - 1, h - 1)
        fg = "#FFFFFF" if self.solid else self.color
        p.setBrush(th.qc(self.color, 255 if self.solid else 26))
        p.setPen(QPen(th.qc(self.color, 255 if self.solid else 90), 1))
        p.drawRoundedRect(r, h / 2, h / 2)
        c = QPointF(22, h / 2)
        if self.pulse:
            a = 0.5 + 0.5 * math.sin(self.phase)
            p.setBrush(th.qc(fg, int(40 + 80 * a)))
            p.setPen(Qt.NoPen)
            p.drawEllipse(c, 6 + 5 * a, 6 + 5 * a)
        p.setBrush(th.qc(fg))
        p.setPen(Qt.NoPen)
        p.drawEllipse(c, 5.5, 5.5)
        p.setPen(th.qc(fg))
        p.setFont(th.font(10.5, 700))
        p.drawText(QRectF(40, 0, w - 50, h), Qt.AlignVCenter | Qt.AlignLeft, self.text)
        p.end()


class Toggle(QWidget):
    """iOS-like switch."""
    toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.checked = False
        self.setFixedSize(44, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.pos_ = 0.0
        self._t = QTimer(self)
        self._t.timeout.connect(self._anim)

    def set_checked(self, on: bool, emit: bool = False):
        self.checked = on
        self._t.start(16)
        if emit:
            self.toggled.emit(on)

    def mouseReleaseEvent(self, e):
        if self.isEnabled() and e.button() == Qt.LeftButton:
            self.toggled.emit(not self.checked)

    def _anim(self):
        target = 1.0 if self.checked else 0.0
        self.pos_ += (target - self.pos_) * 0.35
        if abs(target - self.pos_) < 0.01:
            self.pos_ = target
            self._t.stop()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        on = th.qc(th.ACCENT) if self.isEnabled() else th.qc(th.ACCENT_DIM)
        off = th.qc(th.RAISED)
        c = QColor.fromRgbF(off.redF() + (on.redF() - off.redF()) * self.pos_,
                            off.greenF() + (on.greenF() - off.greenF()) * self.pos_,
                            off.blueF() + (on.blueF() - off.blueF()) * self.pos_)
        p.setBrush(c)
        p.setPen(QPen(th.qc(th.BORDER), 1) if self.pos_ < 0.5 else Qt.NoPen)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), h / 2, h / 2)
        x = 3 + (w - h) * self.pos_
        p.setBrush(th.qc("#F4F7FB" if (self.isEnabled() or self.checked) else th.MUTED))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(x, 3, h - 6, h - 6))
        p.end()


class Banner(QFrame):
    """
    Message strip under the top bar - always there, so nothing below it jumps
    when a fault appears. Idle it shows the last message in grey; a fault
    turns it solid red, a new BIOS violet, a lost link amber.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(16, 0, 8, 0)
        self.lay.setSpacing(12)
        self.icon = QLabel()
        self.icon.setFixedWidth(18)
        self.text = QLabel()
        self.lay.addWidget(self.icon)
        self.lay.addWidget(self.text, 1)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(8)
        self.lay.addLayout(self.buttons)
        self.kind = ""
        self.last_idle = ("", False)
        self.idle("")

    def _clear_buttons(self):
        while self.buttons.count():
            it = self.buttons.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def idle(self, text: str, error: bool = False):
        """Back to the neutral state, showing `text` (status messages)."""
        if text:
            self.last_idle = (text, error)
        else:
            text, error = self.last_idle
        self.kind = ""
        self._clear_buttons()
        self.setStyleSheet("Banner { background:transparent; border:0; border-bottom:1px solid %s; border-radius:0; }"
                           "QLabel { background:transparent; border:0; }" % th.BORDER_SOFT)
        self.icon.setText("●")
        self.icon.setStyleSheet("color:%s;" % (th.RED if error else th.ACCENT_DIM))
        self.icon.setFont(th.font(8, 700))
        if text:
            text = "%s   %s" % (time.strftime("%H:%M"), text)
        self.text.setText(text)
        self.text.setFont(th.font(9.5, 500))
        self.text.setStyleSheet("color:%s;" % (th.RED if error else th.MUTED))

    def show_msg(self, text: str, color: str, icon: str = "●", buttons=(), solid: bool = False):
        self.kind = icon
        if solid:
            bg, border, fg = color, color, "#FFFFFF"
        else:
            bg, border, fg = th.rgba(color, 34), th.rgba(color, 120), color
        self.setStyleSheet("Banner { background:%s; border:1px solid %s; border-radius:12px; }"
                           "QLabel { background:transparent; border:0; color:%s; }" % (bg, border, fg))
        self.icon.setStyleSheet("")
        self.text.setStyleSheet("")
        self.icon.setFont(th.font(13, 800))
        self.icon.setText(icon)
        self.text.setFont(th.font(11 if solid else 10, 700 if solid else 600))
        self.text.setText(text)
        self._clear_buttons()
        for b in buttons:
            self.buttons.addWidget(b)

    def hide_msg(self, kind: str | None = None):
        if kind is None or self.kind == kind:
            self.idle("")
