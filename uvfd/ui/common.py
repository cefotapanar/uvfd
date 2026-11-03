# -*- coding: utf-8 -*-
"""Shared state and small UI helpers used by the main window and the dialogs."""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPalette, QPixmap, QPen, QLinearGradient
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QStyle, QStyledItemDelegate, QStyleOptionComboBox, QStylePainter, QWidget)

from .. import drive as D
from ..catalog import Catalog, Param
from ..i18n import tr
from ..store import FirmwareRegistry, Settings
from . import theme as th


@dataclass
class Ctx:
    """What every window needs: catalog, bus, settings, what we know of the drive."""
    cat: Catalog
    bus: object
    settings: Settings
    fw: FirmwareRegistry
    identity: D.Identity | None = None
    values: dict = field(default_factory=dict)       # code -> raw, latest known
    status: int = -1
    fault: int = 0
    link_text: str = ""
    demo: str | None = None
    absent: set = field(default_factory=set)         # codes this drive did not answer for

    def link_display(self) -> str:
        return self.link_text.replace("DEMO", tr("demo").split(" ")[0])

    @property
    def connected(self) -> bool:
        return self.bus.is_connected and self.identity is not None

    @property
    def running(self) -> bool:
        return self.status in (D.ST_FWD, D.ST_REV)

    def factory(self, p: Param):
        """Factory value: BIOS capture first, then the manual."""
        if self.identity is not None:
            v = (self.fw.versions.get(self.identity.bios_key) or {}).get("factory") or {}
            if p.code in v:
                return v[p.code]
        return p.default


def btn(text: str, kind: str = "", tip: str = "", parent=None) -> QPushButton:
    b = QPushButton(text, parent)
    if kind:
        b.setProperty("kind", kind)
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    return b


def set_prop(w: QWidget, name: str, value):
    w.setProperty(name, value)
    w.style().unpolish(w)
    w.style().polish(w)


def label(text: str = "", obj: str = "", font=None, wrap=False) -> QLabel:
    l = QLabel(text)
    if obj:
        l.setObjectName(obj)
    if font is not None:
        l.setFont(font)
    if wrap:
        l.setWordWrap(True)
    return l


def ask(parent, title: str, text: str, yes: str | None = None, no: str | None = None) -> bool:
    m = QMessageBox(parent)
    m.setWindowTitle(title)
    m.setText(text)
    m.setIcon(QMessageBox.Question)
    by = m.addButton(yes or tr("yes"), QMessageBox.YesRole)
    m.addButton(no or tr("cancel"), QMessageBox.NoRole)
    m.exec()
    return m.clickedButton() is by


def choose(parent, title: str, text: str, options: list[str], default: int = 0) -> int:
    """Several answers; returns the index of the clicked one, -1 for Esc / X."""
    m = QMessageBox(parent)
    m.setWindowTitle(title)
    m.setText(text)
    m.setIcon(QMessageBox.Question)
    buttons = [m.addButton(o, QMessageBox.AcceptRole) for o in options]
    if 0 <= default < len(buttons):
        m.setDefaultButton(buttons[default])
    m.exec()
    clicked = m.clickedButton()
    return buttons.index(clicked) if clicked in buttons else -1


def info(parent, title: str, text: str, warn: bool = False):
    m = QMessageBox(parent)
    m.setWindowTitle(title)
    m.setText(text)
    m.setIcon(QMessageBox.Warning if warn else QMessageBox.Information)
    m.addButton(tr("ok"), QMessageBox.AcceptRole)
    m.exec()


def chip(text: str, color: str, filled: bool = False) -> QLabel:
    l = QLabel(text)
    l.setFont(th.font(8, 700))
    bg = th.rgba(color, 255 if filled else 34)
    fg = "#0A0E13" if filled else color
    l.setStyleSheet("QLabel { background:%s; color:%s; border:1px solid %s; border-radius:9px; padding:2px 8px; }"
                    % (bg, fg, th.rgba(color, 120)))
    return l


def search_box(placeholder: str) -> QLineEdit:
    e = QLineEdit()
    e.setProperty("kind", "search")
    e.setPlaceholderText(placeholder)
    e.setClearButtonEnabled(True)
    ico = QPixmap(18, 18)
    ico.fill(Qt.transparent)
    p = QPainter(ico)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(th.qc(th.MUTED), 1.8))
    p.drawEllipse(3, 3, 9, 9)
    p.drawLine(11, 11, 15, 15)
    p.end()
    e.addAction(QIcon(ico), QLineEdit.LeadingPosition)
    return e


def app_icon(size: int = 256) -> QIcon:
    """The UVFD mark: a rounded tile with a sine wave cut by a drive arc."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    s = size
    g = QLinearGradient(0, 0, s, s)
    g.setColorAt(0, QColor("#16303A"))
    g.setColorAt(1, QColor("#0B141B"))
    p.setBrush(g)
    p.setPen(QPen(QColor("#2BD4BD"), s * 0.03))
    p.drawRoundedRect(s * 0.06, s * 0.06, s * 0.88, s * 0.88, s * 0.22, s * 0.22)
    import math
    path = QPainterPath()
    for k in range(101):
        x = s * 0.2 + s * 0.6 * k / 100
        y = s * 0.5 - s * 0.17 * math.sin(2 * math.pi * k / 100 * 1.5)
        if k == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(QColor("#2BD4BD"), s * 0.075, Qt.SolidLine, Qt.RoundCap))
    p.drawPath(path)
    p.setPen(QPen(QColor("#4EA1FF"), s * 0.05, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(int(s * 0.2), int(s * 0.78), int(s * 0.8), int(s * 0.78))
    p.end()
    return QIcon(pm)


class ElidedCombo(QComboBox):
    """A combo that shows "…" instead of cutting the text, full text as tooltip."""

    def paintEvent(self, _):
        p = QStylePainter(self)
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        p.drawComplexControl(QStyle.CC_ComboBox, opt)
        r = self.style().subControlRect(QStyle.CC_ComboBox, opt, QStyle.SC_ComboBoxEditField, self)
        opt.currentText = self.fontMetrics().elidedText(opt.currentText, Qt.ElideRight, r.width() - 4)
        p.drawControl(QStyle.CE_ComboBoxLabel, opt)

    def setCurrentIndex(self, i):
        super().setCurrentIndex(i)
        self.setToolTip(self.currentText())


class KeepColorDelegate(QStyledItemDelegate):
    """Selected rows keep their meaning colours (changed = amber ...)."""

    def initStyleOption(self, opt, idx):
        super().initStyleOption(opt, idx)
        opt.state &= ~QStyle.State_HasFocus
        opt.state &= ~QStyle.State_MouseOver
        fg = idx.data(Qt.ForegroundRole)
        opt.palette.setBrush(QPalette.HighlightedText, fg if fg is not None else th.qc(th.TEXT))
        opt.palette.setBrush(QPalette.Text, fg if fg is not None else th.qc(th.TEXT))


class ParamEditor(QWidget):
    """Combo for option lists, line edit (+ unit) for numbers."""

    def __init__(self, p: Param, parent=None, compact: bool = False):
        super().__init__(parent)
        self.p = p
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.combo = None
        self.edit = None
        if p.options:
            self.combo = ElidedCombo()
            for n, text in p.options:
                self.combo.addItem(("%d · %s" % (n, text)) if not compact else ("%d · %s" % (n, text))[:46], n)
            self.combo.setMinimumWidth(120)
            lay.addWidget(self.combo, 1)
        else:
            self.edit = QLineEdit()
            self.edit.setAlignment(Qt.AlignRight)
            self.edit.setFont(th.font(10, 600, tabular=True))
            lay.addWidget(self.edit, 1)
            if p.unit:
                u = QLabel(p.unit)
                u.setObjectName("Muted")
                u.setMinimumWidth(22)
                lay.addWidget(u)

    def set_raw(self, raw):
        if self.combo is not None:
            i = self.combo.findData(raw)
            if i < 0 and raw is not None:
                self.combo.addItem("%d · ?" % raw, raw)
                i = self.combo.count() - 1
            self.combo.blockSignals(True)
            self.combo.setCurrentIndex(i)
            self.combo.blockSignals(False)
        elif self.edit is not None:
            self.edit.setText(self.p.fmt(raw))

    def raw(self):
        """Raises ValueError on bad input."""
        if self.combo is not None:
            return self.combo.currentData()
        return self.p.parse(self.edit.text())

    def on_change(self, fn):
        if self.combo is not None:
            self.combo.currentIndexChanged.connect(lambda *_: (self.combo.setToolTip(self.combo.currentText()), fn()))
        else:
            self.edit.textEdited.connect(lambda *_: fn())
