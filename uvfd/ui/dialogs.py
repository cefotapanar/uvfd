# -*- coding: utf-8 -*-
"""Smaller windows: progress, save snapshot, BIOS versions, preferences, update."""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDoubleSpinBox, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QProgressBar, QSpinBox,
                               QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout, QCheckBox, QWidget)

from .. import drive as D
from .. import i18n, updater
from ..bus import job_read, job_scan
from ..i18n import tr
from ..store import SnapshotFile, now_str, save_snapshot
from . import theme as th
from .common import Ctx, KeepColorDelegate, ask, btn, chip, info, label


def short_date(s: str) -> str:
    """'2026-10-31 21:58' -> '31.10 21:58'."""
    try:
        d, t = s.split(" ")
        y, m, dd = d.split("-")
        return "%s.%s %s" % (dd, m, t)
    except ValueError:
        return s


def style_table(t: QTableWidget):
    """The one table look: zebra rows, left headers, no grid, colours kept when selected."""
    t.setAlternatingRowColors(True)
    t.setShowGrid(False)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setItemDelegate(KeepColorDelegate(t))
    t.verticalHeader().setDefaultSectionSize(36)
    t.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    t.horizontalHeader().setHighlightSections(False)


class Dialog(QDialog):
    def __init__(self, parent, title: str, w: int = 520, h: int = 0):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setObjectName("Root")
        self.resize(w, h or 10)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(22, 20, 22, 18)
        self.lay.setSpacing(14)
        t = label(title, font=th.font(14, 700, display=True))
        self.lay.addWidget(t)

    def buttons(self, *bs):
        row = QHBoxLayout()
        row.addStretch(1)
        for b in bs:
            row.addWidget(b)
        self.lay.addLayout(row)


class SafetyStrip(QFrame):
    """Status + output frequency + STOP, shown at the bottom of big dialogs."""

    def __init__(self, ctx: Ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("Card")
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 8, 8, 8)
        h.setSpacing(12)
        self.dot = QLabel("●")
        self.txt = label("", font=th.font(10, 700))
        self.hz = label("", "Muted", th.font(10, 600, tabular=True))
        h.addWidget(self.dot)
        h.addWidget(self.txt)
        h.addWidget(self.hz)
        h.addStretch(1)
        self.stop = btn("■  " + tr("stop"), "stop")
        self.stop.setStyleSheet("QPushButton { padding: 7px 26px; font-size: 10.5pt; }")
        self.stop.clicked.connect(lambda: ctx.bus.command(D.CMD_STOP))
        h.addWidget(self.stop)
        ctx.bus.snapshot.connect(self.on_snap)
        self.on_snap(None)

    def on_snap(self, s):
        if s is not None and s.status == -2:
            return
        on = self.ctx.connected
        self.stop.setEnabled(on)
        if not on:
            col, text = th.FAINT, tr("st_offline")
        elif self.ctx.fault:
            col, text = th.RED, "%s %s" % (tr("st_fault"), D.fault_code_label(self.ctx.fault))
        elif self.ctx.status == D.ST_FWD:
            col, text = th.ACCENT, tr("st_run_fwd")
        elif self.ctx.status == D.ST_REV:
            col, text = th.ACCENT, tr("st_run_rev")
        else:
            col, text = th.MUTED, tr("st_stop")
        self.dot.setStyleSheet("color:%s;" % col)
        self.txt.setStyleSheet("color:%s;" % col)
        self.txt.setText(text)
        if s is not None and s.ok and 0 in s.u0:
            self.hz.setText("%.2f Hz" % (s.u0[0] / 100))

    def detach(self):
        try:
            self.ctx.bus.snapshot.disconnect(self.on_snap)
        except (RuntimeError, TypeError):
            pass


class ProgressDialog(Dialog):
    def __init__(self, parent, title: str, bus, cancel=None):
        super().__init__(parent, title, 460)
        self.setModal(True)
        self.bus = bus
        self.cancel = cancel or bus.cancel_job
        self.bar = QProgressBar()
        self.bar.setFixedHeight(8)
        self.lay.addWidget(self.bar)
        self.txt = label("", "Muted")
        self.lay.addWidget(self.txt)
        c = btn(tr("cancel"), "small")
        c.clicked.connect(self.cancel)
        self.buttons(c)

    def set_progress(self, done: int, total: int, text: str):
        self.bar.setMaximum(max(1, total))
        self.bar.setValue(done)
        self.txt.setText("%s   %d / %d" % (text, done, total))

    def reject(self):
        self.cancel()


class SaveSnapshotDialog(Dialog):
    def __init__(self, parent, ctx: Ctx, values: dict):
        super().__init__(parent, tr("snap_name_title"), 520)
        self.ctx = ctx
        self.values = {k: v for k, v in values.items() if v is not None}
        ident = ctx.identity or D.Identity()
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(10)
        self.ed_name = QLineEdit("BIOS%s_%s" % (ident.bios_key, now_str().replace(":", "").replace(" ", "_")))
        self.ed_name.selectAll()
        self.cb_brand = QComboBox()
        self.cb_brand.setEditable(True)
        for b in ("Winston WSTG600", "SUSWE SU650", ""):
            self.cb_brand.addItem(b)
        last = ctx.settings.get("last_brand")
        if last:
            self.cb_brand.setCurrentText(last)
        self.ed_note = QLineEdit()
        for r, (t, w) in enumerate(((tr("snap_name"), self.ed_name), (tr("snap_brand"), self.cb_brand),
                                    (tr("snap_note"), self.ed_note))):
            g.addWidget(label(t, "Muted"), r, 0)
            g.addWidget(w, r, 1)
        self.lay.addLayout(g)
        summary = "BIOS %s · %s %s · %s · %d" % (ident.bios_key, tr("model"), ident.model_text,
                                                 ident.power_text or "-", len(self.values))
        self.lay.addWidget(label(summary, "Faint"))
        ok = btn(tr("save"), "primary")
        ok.clicked.connect(self.do_save)
        cancel = btn(tr("cancel"))
        cancel.clicked.connect(self.reject)
        self.buttons(cancel, ok)
        self.saved_name, self.saved_count = "", 0

    def do_save(self):
        name = self.ed_name.text().strip()
        if not name:
            self.ed_name.setFocus()
            return
        ident = self.ctx.identity or D.Identity()
        s = SnapshotFile(name=name, values=self.values, note=self.ed_note.text().strip(),
                         brand=self.cb_brand.currentText().strip(),
                         drive={"model": ident.model, "sw": ident.sw, "power": ident.power,
                                "voltage": ident.voltage},
                         link=self.ctx.link_text)
        save_snapshot(s)
        self.ctx.settings["last_brand"] = s.brand
        self.ctx.settings.save()
        self.saved_name, self.saved_count = name, len(self.values)
        self.accept()


class BiosDialog(Dialog):
    def __init__(self, parent, ctx: Ctx):
        super().__init__(parent, tr("bios_window"), 980, 680)
        self.ctx = ctx
        self.lay.addWidget(label(tr("bios_info"), "Muted", wrap=True))
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([tr("col_version"), tr("col_models"), tr("col_seen"),
                                              tr("col_scan"), tr("col_diffs"), tr("col_status")])
        style_table(self.table)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self.show_diff)
        self.lay.addWidget(self.table, 0)
        self.diff = QTableWidget(0, 3)
        self.diff.setHorizontalHeaderLabels([tr("col_code"), tr("col_name"), tr("col_diffs")])
        style_table(self.diff)
        self.diff.verticalHeader().hide()
        self.diff.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.diff.setShowGrid(False)
        self.diff.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.diff.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.diff.horizontalHeader().resizeSection(0, 90)
        self.lay.addWidget(self.diff, 3)
        self.bt_base = btn(tr("set_base"))
        self.bt_base.clicked.connect(self.make_base)
        self.bt_scan = btn(tr("scan_bios"))
        self.bt_scan.clicked.connect(self.scan)
        self.bt_fact = btn(tr("capture_factory"), "", tr("capture_factory_tip"))
        self.bt_fact.clicked.connect(self.capture)
        close = btn(tr("close"))
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        for b in (self.bt_base, self.bt_scan, self.bt_fact):
            row.addWidget(b)
        row.addStretch(1)
        self.status = label("", "Muted")
        row.addWidget(self.status)
        self.lay.addLayout(row)
        foot = QHBoxLayout()
        self.strip = SafetyStrip(ctx)
        foot.addWidget(self.strip, 1)
        foot.addWidget(close)
        self.lay.addLayout(foot)
        ctx.bus.job_progress.connect(self.on_progress)
        ctx.bus.job_done.connect(self.on_done)
        ctx.bus.job_failed.connect(self.on_failed)
        self.fill()

    def codes(self):
        return {p.code for p in self.ctx.cat.params if p.known}

    def fill(self):
        fw = self.ctx.fw
        keys = fw.sorted_keys()
        cur = self.ctx.identity.bios_key if self.ctx.identity else None
        self.table.setRowCount(len(keys))
        for r, k in enumerate(keys):
            v = fw.versions[k]
            nd = len(fw.diff(k, self.codes()))
            cells = ["BIOS " + k, ", ".join(v.get("models", [])),
                     "%s  (%d×)" % (short_date(v.get("last_seen", "")), v.get("seen", 0)),
                     (short_date(v["scan"]["date"]) + " · %d" % len(v["scan"]["present"])) if v.get("scan") else tr("never"),
                     "—" if k == fw.base else str(nd), ""]
            for c, t in enumerate(cells):
                it = QTableWidgetItem(t)
                it.setData(Qt.UserRole, k)
                if c == 0:
                    it.setForeground(th.qc(th.VIOLET))
                    it.setFont(th.font(10, 700))
                self.table.setItem(r, c, it)
            tags = QWidget()
            tl = QHBoxLayout(tags)
            tl.setContentsMargins(6, 0, 6, 0)
            tl.setSpacing(6)
            if k == fw.base:
                tl.addWidget(chip(tr("bios_base"), th.VIOLET))
            if k == cur:
                tl.addWidget(chip("● " + tr("connected"), th.ACCENT))
            if v.get("factory"):
                tl.addWidget(chip(tr("capture_factory") + " ✓", th.MUTED))
            tl.addStretch(1)
            self.table.setCellWidget(r, 5, tags)
        rows_h = self.table.horizontalHeader().height() + 36 * max(1, len(keys)) + 14
        self.table.setFixedHeight(min(rows_h, 260))
        if keys:
            sel = keys.index(cur) if cur in keys else 0
            self.table.selectRow(sel)
        self.update_buttons()

    def selected(self):
        it = self.table.item(self.table.currentRow(), 0)
        return it.data(Qt.UserRole) if it else None

    def update_buttons(self):
        k = self.selected()
        cur = self.ctx.identity.bios_key if (self.ctx.connected and self.ctx.identity) else None
        self.bt_base.setEnabled(bool(k) and k != self.ctx.fw.base)
        self.bt_scan.setEnabled(bool(k) and k == cur)
        self.bt_fact.setEnabled(bool(k) and k == cur)

    def show_diff(self):
        self.update_buttons()
        k = self.selected()
        d = self.ctx.fw.diff(k, self.codes()) if k else {}
        self.diff.setRowCount(len(d))
        from ..catalog import parse_code
        for r, code in enumerate(sorted(d, key=lambda c: parse_code(c))):
            kind, val = d[code]
            p = self.ctx.cat.get(code)
            txt = {"added": tr("bios_added"), "missing": tr("bios_missing"),
                   "factory": tr("bios_factory", p.fmt(val) if p else val)}[kind]
            if kind == "added" and val is not None:
                txt += "  ·  " + tr("value_lbl", p.fmt(val) if p else val)
            col = {"added": th.GREEN, "missing": th.RED, "factory": th.AMBER}[kind]
            name = p.name if (p and p.known and p.name != p.code) else \
                (tr("unknown_param") if not (p and p.known) else tr("no_name"))
            for c, t in enumerate((code, name, txt)):
                it = QTableWidgetItem(t)
                if c == 0:
                    it.setFont(th.font(9, 700, tabular=True))
                    it.setForeground(th.qc(th.MUTED))
                if c == 1 and name.startswith("("):
                    it.setForeground(th.qc(th.FAINT))
                if c == 2:
                    it.setForeground(th.qc(col))
                    it.setFont(th.font(9.5, 700))
                self.diff.setItem(r, c, it)

    def make_base(self):
        k = self.selected()
        if k:
            self.ctx.fw.set_base(k)
            self.fill()

    def scan(self):
        groups = [(g.g, min(99, g.max_index + 8)) for g in self.ctx.cat.groups]
        if self.ctx.bus.start_job("scan:bios", job_scan, groups):
            self.status.setText(tr("scan_bios") + "…")
        else:
            self.status.setText(tr("busy"))

    def capture(self):
        k = self.selected()
        if not ask(self, tr("capture_factory"), tr("capture_confirm", k)):
            return
        if self.ctx.bus.start_job("read:factory", job_read, [p.code for p in self.ctx.cat.params if not p.ro]):
            self.status.setText(tr("read_progress"))
        else:
            self.status.setText(tr("busy"))

    def on_progress(self, tag, done, total, text):
        if tag in ("scan:bios", "read:factory"):
            self.status.setText("%s  %d/%d" % (text, done, total))

    def on_done(self, tag, result):
        k = self.ctx.identity.bios_key if self.ctx.identity else None
        if tag == "scan:bios" and k:
            ranges = {g.g: min(99, g.max_index + 8) for g in self.ctx.cat.groups}
            self.ctx.fw.record_scan(k, result, ranges)
            for code in result:
                self.ctx.cat.ensure(code)
            self.status.setText(tr("scan_done", k, len(result), len(self.ctx.fw.diff(k, self.codes()))))
            self.fill()
        elif tag == "read:factory" and k:
            self.ctx.fw.record_factory(k, {c: v for c, v in result.items() if v is not None})
            self.status.setText("✓")
            self.fill()

    def on_failed(self, tag, err):
        if tag in ("scan:bios", "read:factory"):
            self.status.setText(err)

    def done(self, r):
        self.strip.detach()
        for sig, fn in ((self.ctx.bus.job_progress, self.on_progress), (self.ctx.bus.job_done, self.on_done),
                        (self.ctx.bus.job_failed, self.on_failed)):
            try:
                sig.disconnect(fn)
            except (RuntimeError, TypeError):
                pass
        super().done(r)


class PrefsDialog(Dialog):
    def __init__(self, parent, ctx: Ctx):
        super().__init__(parent, tr("prefs"), 520)
        self.ctx = ctx
        st = ctx.settings
        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(10)
        self.sp_to = QDoubleSpinBox()
        self.sp_to.setRange(0, 60)
        self.sp_to.setDecimals(1)
        self.sp_to.setSingleStep(0.5)
        self.sp_to.setSuffix(" " + tr("seconds"))
        self.sp_to.setValue(float(st.get("comm_timeout") or 0))
        self.sp_poll = QSpinBox()
        self.sp_poll.setRange(100, 2000)
        self.sp_poll.setSingleStep(50)
        self.sp_poll.setSuffix(" ms")
        self.sp_poll.setValue(int(st.get("poll_ms") or 250))
        self.ed_presets = QLineEdit(", ".join("%g" % x for x in st.get("preset_hz") or []))
        self.ck_upd = QCheckBox(tr("check_updates"))
        self.ck_upd.setChecked(bool(st.get("check_updates", True)))
        rows = ((tr("comm_timeout_lbl"), self.sp_to), ("Poll", self.sp_poll),
                ("Presets (Hz)", self.ed_presets), ("", self.ck_upd))
        for r, (t, w) in enumerate(rows):
            g.addWidget(label(t, "Muted"), r, 0)
            g.addWidget(w, r, 1)
        self.lay.addLayout(g)
        self.lay.addWidget(label("PD-04 = 0 → " + ("моторот продолжува ако врската падне" if i18n.lang() == "mk"
                                                  else "the motor keeps running if the link drops"), "Faint"))
        ok = btn(tr("save"), "primary")
        ok.clicked.connect(self.save)
        c = btn(tr("cancel"))
        c.clicked.connect(self.reject)
        self.buttons(c, ok)

    def save(self):
        st = self.ctx.settings
        st["comm_timeout"] = round(self.sp_to.value(), 1)
        st["poll_ms"] = self.sp_poll.value()
        try:
            st["preset_hz"] = [float(x) for x in self.ed_presets.text().replace(";", ",").split(",") if x.strip()][:6]
        except ValueError:
            pass
        st["check_updates"] = self.ck_upd.isChecked()
        st.save()
        if self.ctx.bus.spec is not None:
            self.ctx.bus.spec.comm_timeout = st["comm_timeout"]
        self.accept()


class _DlSignals(QObject):
    progress = Signal(int, int)
    ready = Signal(object)
    failed = Signal(str)


class UpdateDialog(Dialog):
    def __init__(self, parent, rel):
        super().__init__(parent, tr("update_title", rel.version), 560)
        self.rel = rel
        notes = rel.notes.get(i18n.lang()) or rel.notes.get("en") or []
        tb = QTextBrowser()
        tb.setHtml("<ul style='margin-left:-20px'>%s</ul>" % "".join("<li style='margin-bottom:6px'>%s</li>" % n
                                                                    for n in notes))
        tb.setMinimumHeight(160)
        self.lay.addWidget(tb)
        self.bar = QProgressBar()
        self.bar.hide()
        self.lay.addWidget(self.bar)
        self.msg = label("", "Muted", wrap=True)
        self.lay.addWidget(self.msg)
        self.bt_now = btn(tr("update_now"), "primary")
        self.bt_now.clicked.connect(self.go)
        later = btn(tr("update_later"))
        later.clicked.connect(self.reject)
        self.buttons(later, self.bt_now)
        ok, why = updater.can_apply()
        if not ok:
            self.bt_now.setEnabled(False)
            self.msg.setText(tr("update_source") if why == "source" else tr("update_readonly"))
        self.sig = _DlSignals()
        self.sig.progress.connect(self.on_progress)
        self.sig.ready.connect(self.on_ready)
        self.sig.failed.connect(lambda e: (self.msg.setText(tr("update_failed", e)), self.bt_now.setEnabled(True)))

    def go(self):
        self.bt_now.setEnabled(False)
        self.bar.show()

        def work():
            try:
                folder = updater.download(self.rel, on_progress=lambda a, b: self.sig.progress.emit(a, b))
                self.sig.ready.emit(folder)
            except Exception as e:
                self.sig.failed.emit(str(e))
        threading.Thread(target=work, daemon=True).start()

    def on_progress(self, got, total):
        self.bar.setMaximum(max(1, total))
        self.bar.setValue(got)
        if total:
            self.msg.setText(tr("downloading", int(got * 100 / total)))

    def on_ready(self, folder):
        try:
            updater.apply(folder)
        except Exception as e:
            self.msg.setText(tr("update_failed", e))
            return
        self.parent().close()
