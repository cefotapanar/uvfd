# -*- coding: utf-8 -*-
"""
"Which drive is this?" - everything the drive tells about itself (it reports
no kW and no serial number over Modbus, in neither manual), plus a label the
user attaches once to its P7-10 model number, chosen from the manuals' model
tables. And the factory-reset dialog (PP-01 over 0x1F01).
"""

from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QRadioButton, QVBoxLayout, QWidget)

from .. import drive as D
from .. import i18n
from ..i18n import tr
from ..paths import resource
from . import theme as th
from .common import Ctx, btn, label

_MODELS = None


def models() -> list[dict]:
    global _MODELS
    if _MODELS is None:
        try:
            _MODELS = json.loads(resource("models.json").read_text(encoding="utf-8"))["models"]
        except (OSError, ValueError, KeyError):
            _MODELS = []
    return _MODELS


def model_text(m: dict) -> str:
    kw = ("%g" % m["kw"]) + (("/%g" % m["kw_p"]) if m.get("kw_p") else "")
    a = ("%g" % m["out_a"]) + (("/%g" % m["out_a_p"]) if m.get("out_a_p") else "") if m.get("out_a") else ""
    return "%s  ·  %s kW%s  ·  %s" % (m["model"], kw, ("  ·  %s A" % a) if a else "", m.get("supply", ""))


def label_summary(lab: dict | None) -> str:
    if not lab:
        return ""
    s = lab.get("model") or ""
    if lab.get("kw"):
        s += ("  ·  " if s else "") + "%g kW" % lab["kw"]
    return s


class DrivePanel(QWidget):
    """Rows of what is known about the connected drive."""

    def __init__(self, ctx: Ctx, on_edit_label, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.dc = None
        g = QGridLayout(self)
        g.setContentsMargins(0, 4, 0, 0)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(7)
        self.vals = {}
        rows = [("label", tr("label_row")), ("model_no", tr("model_no") + " (P7-10)"),
                ("bios", "BIOS (P7-11)"), ("type", tr("type_row") + " (P0-00)"),
                ("supply", tr("supply_row")), ("rated_v", tr("rated_v_row")),
                ("igbt", tr("igbt_row") + " (P7-07)"), ("motor", tr("motor_row"))]
        for r, (key, title) in enumerate(rows):
            t = label(title, "Muted", th.font(9))
            t.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            g.addWidget(t, r, 0)
            v = label("—", font=th.font(9.5, 600), wrap=True)
            v.setAlignment(Qt.AlignRight | Qt.AlignTop)
            v.setTextFormat(Qt.RichText)
            g.addWidget(v, r, 1)
            self.vals[key] = v
        self.bt_edit = btn("✎  " + tr("set_label"), "small")
        self.bt_edit.clicked.connect(on_edit_label)
        g.addWidget(self.bt_edit, len(rows), 0, 1, 2, Qt.AlignRight)
        g.setColumnStretch(1, 1)
        g.setRowStretch(len(rows) + 1, 1)
        self.refresh()

    def set_dc(self, v):
        self.dc = v
        self.vals["supply"].setText(self._supply())

    def _supply(self) -> str:
        cls = D.supply_class(self.dc)
        if not cls:
            return "—"
        return "%s  <span style='color:%s'>(DC %.0f V)</span>" % (cls, th.FAINT, self.dc)

    def refresh(self):
        ctx = self.ctx
        ident = ctx.identity
        on = ctx.connected and ident is not None
        self.bt_edit.setEnabled(on and ident.model >= 0)
        if not on:
            for v in self.vals.values():
                v.setText("—")
            return
        v = ctx.values
        lab = ctx.fw.model_label(ident.model)
        if lab:
            self.vals["label"].setText("<span style='color:%s'>%s</span>" % (th.ACCENT, label_summary(lab)))
        else:
            self.vals["label"].setText("<span style='color:%s'>%s</span>" % (th.AMBER, tr("label_unknown")))
        self.vals["model_no"].setText(str(ident.model) if ident.model >= 0 else "—")
        self.vals["bios"].setText(ident.bios_key)
        self.vals["type"].setText({1: tr("type_g"), 2: tr("type_p")}.get(ident.gp, "—"))
        rv = v.get("P7-08")
        self.vals["rated_v"].setText("—" if rv is None else ("%d V" % rv if 1 <= rv <= 2000 else
                                                             "%s %d" % (tr("code_word"), rv)))
        t = v.get("P7-07")
        self.vals["igbt"].setText("—" if t is None else "%d °C" % t)
        parts = []
        if v.get("P1-01"):
            parts.append("%g kW" % (v["P1-01"] / 10))
        if v.get("P1-02"):
            parts.append("%d V" % v["P1-02"])
        if v.get("P1-03"):
            parts.append("%.2f A" % (v["P1-03"] / 100))
        if v.get("P1-05"):
            parts.append("%d rpm" % v["P1-05"])
        self.vals["motor"].setText("  ·  ".join(parts) or "—")
        self.vals["supply"].setText(self._supply())


class ModelLabelDialog(QDialog):
    """Attach a model (from the manuals' tables, or free text) to a P7-10 model number."""

    def __init__(self, parent, ctx: Ctx):
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("Root")
        self.setWindowTitle(tr("model_label_title"))
        self.resize(640, 10)
        ident = ctx.identity
        self.model_no = ident.model
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 18)
        v.setSpacing(12)
        v.addWidget(label(tr("model_label_title"), font=th.font(14, 700, display=True)))
        v.addWidget(label(tr("model_label_info", ident.model, ident.bios_key), "Muted", wrap=True))
        self.cb = QComboBox()
        self.cb.setEditable(True)
        self.cb.setInsertPolicy(QComboBox.NoInsert)
        self.cb.addItem("", None)
        for m in models():
            self.cb.addItem(model_text(m), m)
        self.cb.completer().setFilterMode(Qt.MatchContains)
        self.cb.completer().setCompletionMode(self.cb.completer().CompletionMode.PopupCompletion)
        self.kw = QDoubleSpinBox()
        self.kw.setRange(0, 1000)
        self.kw.setDecimals(2)
        self.kw.setSuffix(" kW")
        self.note = QLineEdit()
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(10)
        for r, (t, w) in enumerate(((tr("label_model"), self.cb), (tr("kw_label"), self.kw),
                                    (tr("snap_note"), self.note))):
            g.addWidget(label(t, "Muted"), r, 0)
            g.addWidget(w, r, 1)
        v.addLayout(g)
        self.cb.currentIndexChanged.connect(self.on_pick)
        old = ctx.fw.model_label(self.model_no)
        if old:
            i = self.cb.findText(old.get("model", ""), Qt.MatchStartsWith)
            if i >= 0:
                self.cb.setCurrentIndex(i)
            else:
                self.cb.setEditText(old.get("model", ""))
            self.kw.setValue(float(old.get("kw") or 0))
            self.note.setText(old.get("note", ""))
        row = QHBoxLayout()
        clear = btn(tr("delete"), "danger")
        clear.clicked.connect(self.clear)
        clear.setEnabled(bool(old))
        row.addWidget(clear)
        row.addStretch(1)
        c = btn(tr("cancel"))
        c.clicked.connect(self.reject)
        ok = btn(tr("save"), "primary")
        ok.clicked.connect(self.save)
        row.addWidget(c)
        row.addWidget(ok)
        v.addLayout(row)

    def on_pick(self, _i):
        m = self.cb.currentData()
        if m:
            self.kw.setValue(float(m["kw"]))

    def save(self):
        m = self.cb.currentData()
        text = self.cb.currentText().strip()
        name = m["model"] if m and text == model_text(m) else text.split("  ·  ")[0].strip()
        if not name and not self.kw.value():
            self.cb.setFocus()
            return
        lab = {"model": name, "kw": round(self.kw.value(), 2) or None, "note": self.note.text().strip()}
        if m and name == m["model"]:
            lab.update(out_a=m.get("out_a"), supply=m.get("supply"), series=m.get("series"))
        self.ctx.fw.set_model_label(self.model_no, lab)
        self.accept()

    def clear(self):
        self.ctx.fw.set_model_label(self.model_no, None)
        self.accept()


class FactoryResetDialog(QDialog):
    """Which reset, keep a copy first, optional password. Returns via .result_()"""

    def __init__(self, parent, ctx: Ctx):
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("Root")
        self.setWindowTitle(tr("factory_title"))
        self.resize(620, 10)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 18)
        v.setSpacing(12)
        v.addWidget(label(tr("factory_title"), font=th.font(14, 700, display=True)))
        warn = label(tr("factory_info"), wrap=True)
        warn.setTextFormat(Qt.RichText)
        warn.setStyleSheet("color:%s;" % th.MUTED)
        v.addWidget(warn)
        self.group = QButtonGroup(self)
        for mode, text in ((D.INIT_FACTORY, tr("factory_mode1")), (D.INIT_FACTORY_WITH_MOTOR, tr("factory_mode3")),
                           (D.INIT_CLEAR_FAULTS, tr("factory_mode2"))):
            rb = QRadioButton(text)
            rb.setFont(th.font(10, 600 if mode == D.INIT_FACTORY else 400))
            self.group.addButton(rb, mode)
            v.addWidget(rb)
        self.group.button(D.INIT_FACTORY).setChecked(True)
        self.keep = QCheckBox(tr("factory_keep"))
        self.keep.setChecked(True)
        v.addWidget(self.keep)
        pw = QHBoxLayout()
        pw.addWidget(label(tr("factory_password"), "Muted"))
        self.pwd = QLineEdit()
        self.pwd.setPlaceholderText(tr("factory_password_hint"))
        self.pwd.setMaxLength(5)
        self.pwd.setFixedWidth(140)
        pw.addWidget(self.pwd)
        pw.addStretch(1)
        v.addLayout(pw)
        self.err = label("", wrap=True)
        self.err.setStyleSheet("color:%s;" % th.RED)
        v.addWidget(self.err)
        row = QHBoxLayout()
        row.addStretch(1)
        c = btn(tr("cancel"))
        c.clicked.connect(self.reject)
        go = btn("↺  " + tr("factory_go"), "danger")
        go.setStyleSheet("QPushButton { padding: 8px 16px; font-size: 10pt; }")
        go.clicked.connect(self.go)
        row.addWidget(c)
        row.addWidget(go)
        v.addLayout(row)
        self.choice = None

    def go(self):
        txt = self.pwd.text().strip()
        if txt and not txt.isdigit():
            self.err.setText(tr("factory_password_bad"))
            return
        if self.ctx.running:
            self.err.setText(tr("need_stop"))
            return
        self.choice = (self.group.checkedId(), self.keep.isChecked(), int(txt) if txt else None)
        self.accept()
