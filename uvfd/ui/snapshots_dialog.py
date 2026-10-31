# -*- coding: utf-8 -*-
"""
Load: saved parameter sets. Pick one, compare it with the drive, tick what to
write, write it in the safe order (P0-10 first, then the limits, the motor
group, the rest), every value read back and verified.
"""

from __future__ import annotations

import csv
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QFileDialog, QFrame, QHBoxLayout,
                               QHeaderView, QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from .. import i18n, store
from ..bus import WriteItem, job_read, job_write
from ..catalog import parse_code
from ..i18n import tr
from . import theme as th
from .common import Ctx, KeepColorDelegate, ask, btn, chip, info, label, search_box
from .dialogs import SafetyStrip


class SnapshotsDialog(QDialog):
    def __init__(self, parent, ctx: Ctx):
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("Root")
        self.setWindowTitle(tr("load_title"))
        pw = parent.size() if parent else QSize(1400, 860)
        self.resize(int(pw.width() * 0.9), int(pw.height() * 0.88))
        self.snaps: list[store.SnapshotFile] = []
        self.cur: store.SnapshotFile | None = None
        self.drive_vals: dict | None = None
        self.rows: list[tuple] = []

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 14)
        v.setSpacing(12)
        head = QHBoxLayout()
        head.addWidget(label(tr("load_title"), font=th.font(15, 700, display=True)))
        head.addStretch(1)
        imp = btn(tr("import_vfdtool"), "small")
        imp.clicked.connect(self.import_old)
        head.addWidget(imp)
        v.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(8)
        self.search = search_box(tr("search_sets"))
        self.search.textChanged.connect(self.fill_list)
        left.addWidget(self.search)
        self.list = QListWidget()
        self.list.setFixedWidth(330)
        self.list.setSpacing(2)
        self.list.currentRowChanged.connect(self.on_pick)
        left.addWidget(self.list, 1)
        lb = QHBoxLayout()
        self.bt_del = btn("✕  " + tr("delete"), "danger")
        self.bt_del.clicked.connect(self.delete)
        self.bt_csv = btn("⤓  " + tr("export_csv"), "small")
        self.bt_csv.clicked.connect(self.export_csv)
        lb.addWidget(self.bt_csv)
        lb.addStretch(1)
        lb.addWidget(self.bt_del)
        left.addLayout(lb)
        body.addLayout(left)

        right = QVBoxLayout()
        right.setSpacing(10)
        self.hdr = QFrame()
        self.hdr.setObjectName("Card")
        hl = QHBoxLayout(self.hdr)
        hl.setContentsMargins(16, 12, 16, 12)
        self.lbl_title = label("", font=th.font(13, 700, display=True))
        self.lbl_meta = label("", "Muted", wrap=True)
        tv = QVBoxLayout()
        tv.addWidget(self.lbl_title)
        tv.addWidget(self.lbl_meta)
        hl.addLayout(tv, 1)
        self.bt_compare = btn("⇄  " + tr("compare"), "primary")
        self.bt_compare.clicked.connect(self.compare)
        hl.addWidget(self.bt_compare)
        right.addWidget(self.hdr)
        self.warn = label("", wrap=True)
        self.warn.hide()
        right.addWidget(self.warn)
        self.table = QTableWidget(0, 5)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setItemDelegate(KeepColorDelegate(self.table))
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        right.addWidget(self.table, 1)
        wr = QHBoxLayout()
        self.lbl_count = label("", "Muted")
        wr.addWidget(self.lbl_count)
        wr.addStretch(1)
        self.lbl_prog = label("", "Muted")
        wr.addWidget(self.lbl_prog)
        self.bt_write = btn(tr("write_selected"), "primary")
        self.bt_write.clicked.connect(self.write)
        self.bt_write.setEnabled(False)
        wr.addWidget(self.bt_write)
        right.addLayout(wr)
        body.addLayout(right, 1)
        v.addLayout(body, 1)

        bottom = QHBoxLayout()
        self.strip = SafetyStrip(ctx)
        bottom.addWidget(self.strip, 1)
        close = btn(tr("close"))
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        v.addLayout(bottom)

        ctx.bus.job_progress.connect(self.on_progress)
        ctx.bus.job_done.connect(self.on_done)
        ctx.bus.job_failed.connect(self.on_failed)
        self.reload()

    # ---------------------------------------------------------------- list
    def reload(self):
        self.snaps = store.list_snapshots()
        self.fill_list()

    def fill_list(self):
        q = self.search.text().lower().strip()
        self.list.blockSignals(True)
        self.list.clear()
        self.visible = []
        for s in self.snaps:
            hay = " ".join((s.name, s.note, s.brand, s.date, "bios " + s.bios)).lower()
            if q and not all(part in hay for part in q.split()):
                continue
            it = QListWidgetItem()
            w = QWidget()
            l = QVBoxLayout(w)
            l.setContentsMargins(12, 8, 12, 8)
            l.setSpacing(2)
            l.addWidget(label(s.name, font=th.font(10, 700)))
            l.addWidget(label("%s · BIOS %s%s" % (s.date, s.bios, (" · " + s.brand) if s.brand else ""),
                              "Muted", th.font(8.5)))
            if s.note:
                l.addWidget(label(s.note, "Faint", th.font(8.5)))
            it.setSizeHint(w.sizeHint() + QSize(0, 4))
            self.list.addItem(it)
            self.list.setItemWidget(it, w)
            self.visible.append(s)
        self.list.blockSignals(False)
        if self.visible:
            self.list.setCurrentRow(0)
            self.on_pick(0)
        else:
            self.on_pick(-1)

    def on_pick(self, row: int):
        self.cur = self.visible[row] if 0 <= row < len(self.visible) else None
        self.drive_vals = None
        self.warn.hide()
        self.bt_write.setEnabled(False)
        self.bt_del.setEnabled(self.cur is not None)
        self.bt_csv.setEnabled(self.cur is not None)
        self.bt_compare.setEnabled(self.cur is not None and self.ctx.connected)
        if self.cur is None:
            self.lbl_title.setText("—")
            self.lbl_meta.setText("")
            self.table.setRowCount(0)
            return
        s = self.cur
        self.lbl_title.setText(s.name)
        d = s.drive
        meta = ["BIOS %s" % s.bios]
        if d.get("model", -1) >= 0:
            meta.append("%s %.2f" % (tr("model"), d["model"] / 100))
        if d.get("power", -1) > 0:
            meta.append("%.1f kW" % (d["power"] / 10))
        for x in (s.brand, s.date, s.note, s.link):
            if x:
                meta.append(x)
        meta.append("%d" % len(s.values))
        self.lbl_meta.setText("  ·  ".join(meta))
        self.show_values()

    def show_values(self):
        s = self.cur
        self.table.clear()
        self.table.setColumnCount(3)
        self.set_headers([tr("col_code"), tr("col_name"), tr("col_saved")], right={2})
        codes = sorted(s.values, key=lambda c: parse_code(c) or (99, 0))
        self.table.setRowCount(len(codes))
        for r, code in enumerate(codes):
            p = self.ctx.cat.get(code)
            raw = s.values[code]
            self._set(r, 0, code, th.FAINT, bold=True)
            self._set(r, 1, p.name if p else "?")
            self._set(r, 2, self.fmt(p, raw), align=Qt.AlignRight)
        h = self.table.horizontalHeader()
        for c in range(self.table.columnCount()):
            h.setSectionResizeMode(c, QHeaderView.Interactive)
        h.resizeSection(0, 72)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        h.resizeSection(2, 220)
        self.lbl_count.setText("%d" % len(codes))

    def set_headers(self, names, right=()):
        for c, n in enumerate(names):
            it = QTableWidgetItem(n)
            it.setTextAlignment(int((Qt.AlignRight if c in right else Qt.AlignLeft) | Qt.AlignVCenter))
            self.table.setHorizontalHeaderItem(c, it)

    def fmt(self, p, raw):
        if raw is None:
            return "—"
        if p is None:
            return str(raw)
        if p.options:
            t = p.option_text(raw)
            return "%d · %s" % (raw, t) if t else str(raw)
        return p.fmt(raw, True)

    def _set(self, r, c, text, color=None, bold=False, align=None):
        it = QTableWidgetItem(text)
        if color:
            it.setForeground(th.qc(color))
        if bold:
            it.setFont(th.font(9, 700, tabular=True))
        if align is not None:
            it.setTextAlignment(int(align | Qt.AlignVCenter))
        self.table.setItem(r, c, it)
        return it

    # ---------------------------------------------------------------- compare
    def compare(self):
        if not (self.cur and self.ctx.connected):
            return
        if self.ctx.bus.start_job("snap:read", job_read, list(self.cur.values)):
            self.lbl_prog.setText(tr("read_progress"))
        else:
            self.lbl_prog.setText(tr("busy"))

    def show_compare(self):
        s, dv = self.cur, self.drive_vals
        ident = self.ctx.identity
        if ident and s.bios not in ("?", ident.bios_key):
            self.warn.setText("◆  " + tr("bios_mismatch", s.bios, ident.bios_key))
            self.warn.setStyleSheet("color:%s; background:%s; border:1px solid %s; border-radius:10px; padding:10px;"
                                    % (th.AMBER, th.rgba(th.AMBER, 26),
                                       th.rgba(th.AMBER, 90)))
            self.warn.show()
        self.rows = []
        for code in sorted(s.values, key=lambda c: parse_code(c) or (99, 0)):
            p = self.ctx.cat.get(code)
            want, have = s.values[code], dv.get(code)
            if have == want:
                continue
            if p is None:
                act, ok = tr("act_skip_absent"), False
            elif p.ro:
                act, ok = tr("act_skip_ro"), False
            elif have is None:
                act, ok = tr("act_skip_absent"), False
            elif p.g == 0x0D:
                act, ok = tr("act_skip_comm"), False
            elif p.model_dep:
                act, ok = tr("act_skip_model"), None          # allowed, unticked
            else:
                act, ok = tr("act_write"), True
            self.rows.append((code, p, want, have, act, ok))
        self.table.clear()
        self.table.setColumnCount(6)
        self.set_headers(["", tr("col_code"), tr("col_name"), tr("col_drive"), tr("col_saved"), tr("col_action")],
                         right={3, 4})
        self.table.setRowCount(len(self.rows))
        self.checks = []
        for r, (code, p, want, have, act, ok) in enumerate(self.rows):
            cb = QCheckBox()
            cb.setChecked(ok is True)
            cb.setEnabled(ok is not False)
            cb.stateChanged.connect(self.update_count)
            cw = QWidget()
            cl = QHBoxLayout(cw)
            cl.setContentsMargins(10, 0, 0, 0)
            cl.addWidget(cb)
            self.table.setCellWidget(r, 0, cw)
            self.checks.append(cb)
            self._set(r, 1, code, th.FAINT, bold=True)
            self._set(r, 2, p.name if p else tr("unknown_param"))
            self._set(r, 3, self.fmt(p, have), th.MUTED, align=Qt.AlignRight)
            self._set(r, 4, self.fmt(p, want), th.AMBER, bold=True, align=Qt.AlignRight)
            badge = {tr("act_write"): tr("b_write"), tr("act_skip_model"): tr("b_model"),
                     tr("act_skip_comm"): tr("b_comm"), tr("act_skip_ro"): tr("b_ro"),
                     tr("act_skip_absent"): tr("b_absent")}.get(act, act)
            it = self._set(r, 5, ("●  " if ok else "○  ") + badge,
                           th.ACCENT if ok else (th.AMBER if ok is None else th.FAINT), bold=bool(ok))
            it.setToolTip(act)
        h = self.table.horizontalHeader()
        for c in range(self.table.columnCount()):
            h.setSectionResizeMode(c, QHeaderView.Interactive)
        h.resizeSection(0, 44)
        h.resizeSection(1, 72)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        h.resizeSection(3, 190)
        h.resizeSection(4, 190)
        h.resizeSection(5, 150)
        if not self.rows:
            self.lbl_count.setText(tr("no_diff"))
        self.update_count()

    def update_count(self):
        n = sum(1 for c in getattr(self, "checks", []) if c.isChecked())
        if self.rows:
            self.lbl_count.setText(tr("diff_count", len(self.rows), n))
        self.bt_write.setEnabled(n > 0 and self.ctx.connected)

    def write(self):
        items = [WriteItem(self.rows[k][1], self.rows[k][2]) for k, c in enumerate(self.checks) if c.isChecked()]
        if not items:
            return
        if self.ctx.running:
            info(self, tr("write_selected"), tr("need_stop"), warn=True)
            return
        if not ask(self, tr("write_selected"), tr("diff_count", len(self.rows), len(items)) + "\n\n" + tr("write") + "?"):
            return
        if self.ctx.bus.start_job("snap:write", job_write, items, True):
            self.bt_write.setEnabled(False)
        else:
            self.lbl_prog.setText(tr("busy"))

    # ---------------------------------------------------------------- jobs
    def on_progress(self, tag, done, total, text):
        if tag in ("snap:read", "snap:write"):
            self.lbl_prog.setText("%s  %d / %d" % (text, done, total))

    def on_done(self, tag, result):
        if tag == "snap:read":
            self.lbl_prog.setText("")
            self.drive_vals = result
            self.show_compare()
        elif tag == "snap:write":
            ok = sum(1 for r in result if r.status == "ok")
            same = sum(1 for r in result if r.status == "same")
            bad = [r for r in result if r.status not in ("ok", "same")]
            self.lbl_prog.setText(tr("write_report", ok, same, len(bad)))
            if bad:
                info(self, tr("write_selected"), tr("write_report", ok, same, len(bad)) + "\n\n" +
                     "\n".join("%s: %s" % (r.code, r.detail or r.status) for r in bad[:20]), warn=True)
            self.compare()

    def on_failed(self, tag, err):
        if tag in ("snap:read", "snap:write"):
            self.lbl_prog.setText("✕ " + err)
            self.update_count()

    # ---------------------------------------------------------------- files
    def delete(self):
        if self.cur and ask(self, tr("delete"), tr("delete_confirm", self.cur.name), tr("delete")):
            store.delete_snapshot(self.cur)
            self.reload()

    def export_csv(self):
        if not self.cur:
            return
        fn, _ = QFileDialog.getSaveFileName(self, "CSV", str(Path.home() / (store.slug(self.cur.name) + ".csv")),
                                            "CSV (*.csv)")
        if not fn:
            return
        with open(fn, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["code", "address", "parameter", "value", "unit", "raw", "factory"])
            for code in sorted(self.cur.values, key=lambda c: parse_code(c) or (99, 0)):
                p = self.ctx.cat.get(code)
                raw = self.cur.values[code]
                w.writerow([code, "0x%04X" % p.address if p else "", p.name if p else "",
                            p.fmt(raw) if p else raw, p.unit if p else "", raw,
                            "" if not p or p.default is None else p.fmt(p.default)])
        self.lbl_prog.setText("✓ " + Path(fn).name)

    def import_old(self):
        start = r"C:\Users\cefot\Desktop\Stvari\AI\VFDTool\vfdtool_profiles.txt"
        fn, _ = QFileDialog.getOpenFileName(self, tr("import_vfdtool"), start if Path(start).exists() else "",
                                            "VFDTool (*.txt)")
        if not fn:
            return
        n = 0
        for s in store.import_vfdtool(Path(fn)):
            store.save_snapshot(s)
            n += 1
        self.reload()
        self.lbl_prog.setText("✓ %d" % n)

    def done(self, r):
        self.strip.detach()
        for sig, fn in ((self.ctx.bus.job_progress, self.on_progress), (self.ctx.bus.job_done, self.on_done),
                        (self.ctx.bus.job_failed, self.on_failed)):
            try:
                sig.disconnect(fn)
            except (RuntimeError, TypeError):
                pass
        super().done(r)
