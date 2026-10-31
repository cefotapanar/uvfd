# -*- coding: utf-8 -*-
"""
Settings window: categories on the left, the parameter table in the middle,
the selected parameter on the right (value, editor, range, options, the
manual's description), search on top, and one column per BIOS version that
differs from the base - only where it differs.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QFontMetricsF, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QListWidget, QListWidgetItem, QScrollArea, QStyle, QStyledItemDelegate,
                               QTableView, QTextBrowser, QVBoxLayout, QWidget)

from .. import i18n
from ..bus import WriteItem, job_read, job_write
from ..catalog import Param
from ..i18n import tr
from . import theme as th
from .common import Ctx, KeepColorDelegate, ParamEditor, ask, btn, chip, info, label, search_box
from .dialogs import SafetyStrip

COMM_LINK = {"PD-00", "PD-01", "PD-02", "PD-05"}


# ============================================================ nav

def display_name(p: Param) -> str:
    if not p.known:
        return "%s  %s" % (p.code, tr("unknown_param"))
    if p.name == p.code:
        return tr("no_name")
    return p.name


class NavDelegate(QStyledItemDelegate):
    def paint(self, p: QPainter, opt, idx):
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(opt.rect).adjusted(2, 1, -2, -1)
        sel = opt.state & QStyle.State_Selected
        hov = opt.state & QStyle.State_MouseOver
        kind = idx.data(Qt.UserRole + 2)
        if kind == "sep":
            p.setPen(th.qc(th.BORDER_SOFT))
            p.drawLine(r.left() + 8, r.center().y(), r.right() - 8, r.center().y())
            p.restore()
            return
        if sel or hov:
            p.setPen(Qt.NoPen)
            p.setBrush(th.qc(th.RAISED if sel else th.SURFACE2))
            p.drawRoundedRect(r, 8, 8)
        if sel:
            p.setBrush(th.qc(th.ACCENT))
            p.drawRoundedRect(QRectF(r.left(), r.top() + 8, 3, r.height() - 16), 1.5, 1.5)
        code = idx.data(Qt.UserRole + 1) or ""
        x = r.left() + 12
        if code:
            p.setFont(th.font(8, 700))
            p.setPen(th.qc(th.VIOLET if kind == "bios" else (th.ACCENT if sel else th.FAINT)))
            p.drawText(QRectF(x, r.top(), 28, r.height()), Qt.AlignVCenter | Qt.AlignLeft, code)
            x += 30
        p.setFont(th.font(9.5, 600 if sel else 500))
        p.setPen(th.qc(th.TEXT if sel else th.MUTED))
        count = idx.data(Qt.UserRole + 3)
        p.drawText(QRectF(x, r.top(), r.right() - x - 34, r.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   idx.data(Qt.DisplayRole))
        if count is not None:
            p.setFont(th.font(8, 600, tabular=True))
            p.setPen(th.qc(th.FAINT if kind != "changed" or not count else th.AMBER))
            p.drawText(QRectF(r.right() - 40, r.top(), 32, r.height()), Qt.AlignVCenter | Qt.AlignRight, str(count))
        p.restore()

    def sizeHint(self, opt, idx):
        return QSize(200, 12 if idx.data(Qt.UserRole + 2) == "sep" else 36)


# ============================================================ table model

class ParamModel(QAbstractTableModel):
    BASE_COLS = 5

    def __init__(self, ctx: Ctx):
        super().__init__()
        self.ctx = ctx
        self.rows: list[Param] = []
        self.bios_cols: list[tuple[str, dict]] = []

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = rows
        known = {p.code for p in self.ctx.cat.params if p.known}
        codes = {p.code for p in rows}
        # a version gets its column only where these rows actually differ
        self.bios_cols = [(k, d) for k, d in self.ctx.fw.all_diffs(known).items() if codes & set(d)]
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return self.BASE_COLS + len(self.bios_cols)

    def headerData(self, s, orient, role=Qt.DisplayRole):
        if orient != Qt.Horizontal:
            return None
        if role == Qt.DisplayRole:
            if s < self.BASE_COLS:
                return [tr("col_code"), tr("col_name"), tr("col_value"), tr("col_unit"), tr("col_factory")][s]
            key = self.bios_cols[s - self.BASE_COLS][0]
            return "◆ BIOS %s" % key
        if role == Qt.ForegroundRole and s >= self.BASE_COLS:
            return th.qc(th.VIOLET)
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignRight | Qt.AlignVCenter) if s in (2, 4) else int(Qt.AlignLeft | Qt.AlignVCenter)
        return None

    def value_text(self, p: Param, raw) -> str:
        if raw is None:
            return "—"
        if p.options:
            t = p.option_text(raw)
            return "%d · %s" % (raw, t) if t else str(raw)
        return p.fmt(raw)

    def changed(self, p: Param) -> bool:
        raw = self.ctx.values.get(p.code)
        f = self.ctx.factory(p)
        if raw is None or f is None or p.ro or p.composite:
            return False
        a = raw - 65536 if p.signed and raw > 32767 else raw
        b = f - 65536 if p.signed and f > 32767 else f
        return a != b

    def data(self, idx, role=Qt.DisplayRole):
        p = self.rows[idx.row()]
        c = idx.column()
        raw = self.ctx.values.get(p.code)
        if role == Qt.DisplayRole:
            if c == 0:
                return ("● " if self.changed(p) else "   ") + p.code
            if c == 1:
                return display_name(p)
            if c == 2:
                return self.value_text(p, raw)
            if c == 3:
                return p.unit
            if c == 4:
                f = self.ctx.factory(p)
                return "" if f is None else (str(f) if p.options else p.fmt(f))
            key, d = self.bios_cols[c - self.BASE_COLS]
            if p.code in d:
                kind, val = d[p.code]
                return {"added": tr("bios_added"), "missing": tr("bios_missing"),
                        "factory": tr("bios_factory", p.fmt(val))}[kind]
            return ""
        if role == Qt.ForegroundRole:
            if c == 0:
                return th.qc(th.AMBER if self.changed(p) else th.FAINT)
            if c == 2:
                if raw is None:
                    return th.qc(th.FAINT)
                if p.ro:
                    return th.qc(th.BLUE)
                return th.qc(th.AMBER if self.changed(p) else th.TEXT)
            if c == 3:
                return th.qc(th.FAINT)
            if c == 4:
                return th.qc(th.MUTED if self.changed(p) else th.FAINT)
            if c == 1 and (not p.known or p.name == p.code):
                return th.qc(th.VIOLET if not p.known else th.FAINT)
            if c >= self.BASE_COLS:
                d = self.bios_cols[c - self.BASE_COLS][1]
                kind = d.get(p.code, ("",))[0]
                return th.qc({"added": th.GREEN, "missing": th.RED, "factory": th.AMBER}.get(kind, th.MUTED))
        if role == Qt.FontRole:
            if c == 0:
                return th.font(9, 700, tabular=True)
            if c == 2:
                return th.font(10, 700 if self.changed(p) else 600, tabular=True)
            if c >= self.BASE_COLS:
                return th.font(8.5, 700)
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignRight | Qt.AlignVCenter) if c in (2, 4) else int(Qt.AlignLeft | Qt.AlignVCenter)
        if role == Qt.ToolTipRole and c == 1:
            return p.name
        if role == Qt.ToolTipRole and c == 2:
            return self.value_text(p, raw)
        return None


# ============================================================ the window

class SetupDialog(QDialog):
    def __init__(self, parent, ctx: Ctx, category: str | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("Root")
        self.setWindowTitle(tr("setup_title"))
        pw = parent.size() if parent else QSize(1400, 860)
        self.resize(int(pw.width() * 0.94), int(pw.height() * 0.92))
        self.current: Param | None = None
        self.category = category or "g0"

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 14)
        v.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(12)
        title = label(tr("setup_title"), font=th.font(15, 700, display=True))
        head.addWidget(title)
        head.addSpacing(10)
        self.search = search_box(tr("search"))
        self.search.setMinimumWidth(420)
        self.search.textChanged.connect(self.on_search)
        head.addWidget(self.search, 1)
        self.lbl_prog = label("", "Muted")
        head.addWidget(self.lbl_prog)
        self.bt_read = btn("⟳  " + tr("read_group"), "small")
        self.bt_read.clicked.connect(self.read_current)
        self.bt_read_all = btn("⤓  " + tr("read_all"), "small")
        self.bt_read_all.clicked.connect(self.read_all)
        head.addWidget(self.bt_read)
        head.addWidget(self.bt_read_all)
        v.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(14)
        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setItemDelegate(NavDelegate())
        self.nav.setFixedWidth(236)
        self.nav.setMouseTracking(True)
        self.nav.currentItemChanged.connect(self.on_nav)
        body.addWidget(self.nav)

        self.model = ParamModel(ctx)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setMouseTracking(True)
        self.table.setItemDelegate(KeepColorDelegate(self.table))
        self.table.selectionModel().currentRowChanged.connect(self.on_row)
        body.addWidget(self.table, 1)

        self.detail = QScrollArea()
        self.detail.setWidgetResizable(True)
        self.detail.setFrameShape(QFrame.NoFrame)
        self.detail.setFixedWidth(384)
        body.addWidget(self.detail)
        v.addLayout(body, 1)

        bottom = QHBoxLayout()
        self.strip = SafetyStrip(ctx)
        bottom.addWidget(self.strip, 1)
        close = btn(tr("close"))
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        v.addLayout(bottom)

        QShortcut(QKeySequence.Find, self, activated=lambda: (self.search.setFocus(), self.search.selectAll()))

        ctx.bus.values.connect(self.on_values)
        ctx.bus.job_progress.connect(self.on_progress)
        ctx.bus.job_done.connect(self.on_done)
        ctx.bus.job_failed.connect(self.on_failed)

        self.fill_nav()
        self.show_detail(None)
        self.on_nav(self.nav.currentItem(), None)
        self.update_enabled()

    # ---------------------------------------------------------------- nav
    def fill_nav(self):
        self.nav.blockSignals(True)
        cur = self.category
        self.nav.clear()
        lang = i18n.lang()

        def add(key, text, code="", count=None, kind=""):
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, key)
            it.setData(Qt.UserRole + 1, code)
            it.setData(Qt.UserRole + 2, kind)
            it.setData(Qt.UserRole + 3, count)
            if kind == "sep":
                it.setFlags(Qt.NoItemFlags)
            self.nav.addItem(it)
        add("all", tr("cat_all"), "★", len(self.ctx.cat.params))
        add("changed", tr("cat_changed"), "≠", self.count_changed(), "changed")
        known = {p.code for p in self.ctx.cat.params if p.known}
        diffs = self.ctx.fw.all_diffs(known)
        if diffs:
            add("bios", tr("cat_bios"), "◆", len(set().union(*[set(d) for d in diffs.values()])), "bios")
        add("sep", "", kind="sep")
        for g in self.ctx.cat.groups:
            add("g%d" % g.g, g.title(lang), g.id, len(self.ctx.cat.group(g.g)))
        self.nav.blockSignals(False)
        self.select_category(cur, refresh=False)

    def count_changed(self) -> int:
        return sum(1 for p in self.ctx.cat.params if self.model.changed(p)) if hasattr(self, "model") else 0

    def select_category(self, key: str, refresh: bool = True):
        for i in range(self.nav.count()):
            if self.nav.item(i).data(Qt.UserRole) == key:
                self.nav.blockSignals(not refresh)
                self.nav.setCurrentRow(i)
                self.nav.blockSignals(False)
                return

    def on_nav(self, cur, _prev):
        if cur is None:
            return
        key = cur.data(Qt.UserRole)
        if key == "sep":
            return
        self.category = key
        if self.search.text():
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
        self.refresh_rows()
        if key.startswith("g") and self.ctx.connected:
            g = int(key[1:])
            if any(self.ctx.values.get(p.code) is None for p in self.ctx.cat.group(g)):
                self.read_current()

    def rows_for(self, key: str) -> list[Param]:
        cat = self.ctx.cat
        if key == "all":
            return list(cat.params)
        if key == "changed":
            return [p for p in cat.params if self.model.changed(p)]
        if key == "bios":
            known = {p.code for p in cat.params if p.known}
            codes = set()
            for d in self.ctx.fw.all_diffs(known).values():
                codes |= set(d)
            return [cat.ensure(c) for c in sorted(codes, key=lambda c: (cat.ensure(c).g, cat.ensure(c).i))]
        if key.startswith("g"):
            return cat.group(int(key[1:]))
        return []

    def refresh_rows(self, keep: bool = True):
        q = self.search.text().strip()
        rows = [p for p in self.ctx.cat.params if p.matches(q)] if q else self.rows_for(self.category)
        cur = self.current.code if (keep and self.current) else None
        self.model.set_rows(rows)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Fixed)
        h.resizeSection(0, 78)
        h.setSectionResizeMode(1, QHeaderView.Interactive)
        h.resizeSection(1, 270)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        h.resizeSection(3, 46)
        h.resizeSection(4, 74)
        for c in range(ParamModel.BASE_COLS, self.model.columnCount()):
            h.resizeSection(c, 96)
        if cur:
            for r, p in enumerate(rows):
                if p.code == cur:
                    self.table.selectRow(r)
                    break

    def on_search(self, text: str):
        self.refresh_rows(keep=False)
        if text and self.model.rowCount():
            self.table.selectRow(0)

    # ---------------------------------------------------------------- detail
    def on_row(self, cur, _prev):
        if not cur.isValid() or cur.row() >= len(self.model.rows):
            self.show_detail(None)
            return
        self.show_detail(self.model.rows[cur.row()])

    def show_detail(self, p: Param | None):
        self.current = p
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 0, 6, 0)
        lay.setSpacing(12)
        if p is None:
            lay.addStretch(1)
            hint = label(tr("no_selection"), "Faint")
            hint.setAlignment(Qt.AlignCenter)
            lay.addWidget(hint)
            lay.addStretch(2)
            self.detail.setWidget(w)
            return
        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(18, 16, 18, 18)
        cl.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(label(p.code, font=th.font(12, 800, tabular=True)))
        top.addWidget(label("0x%04X" % p.address, "Faint", th.font(8.5, 600, tabular=True)))
        top.addStretch(1)
        if p.ro:
            top.addWidget(chip(tr("flag_ro"), th.BLUE))
        if p.stop_only:
            top.addWidget(chip(tr("only_stopped").upper(), th.AMBER))
        if p.model_dep:
            top.addWidget(chip(tr("b_model"), th.MUTED))
        cl.addLayout(top)
        nm = label(display_name(p), font=th.font(13.5, 700, display=True), wrap=True)
        if p.name == p.code or not p.known:
            nm.setStyleSheet("color:%s;" % th.MUTED)
        cl.addWidget(nm)
        flags = []
        if p.model_dep:
            flags.append(tr("flag_model"))
        if not p.known:
            flags.append(tr("flag_unknown"))
        if flags:
            cl.addWidget(label(" · ".join(flags), "Muted", th.font(8.5), wrap=True))

        raw = self.ctx.values.get(p.code)
        f = self.ctx.factory(p)
        vrow = QHBoxLayout()
        if raw is None:
            vrow.addWidget(label(tr("b_absent") if p.code in self.ctx.absent else tr("not_read"), "Muted",
                                 th.font(11, 600)), 0, Qt.AlignBaseline)
        else:
            big = label(self.model.value_text(p, raw) if not p.options else str(raw),
                        font=th.font(24, 600, display=True, tabular=True))
            big.setStyleSheet("color:%s;" % (th.AMBER if self.model.changed(p) else th.TEXT))
            vrow.addWidget(big, 0, Qt.AlignBaseline)
            if p.unit:
                vrow.addWidget(label(p.unit, "Muted", th.font(12, 600)), 0, Qt.AlignBaseline)
        vrow.addStretch(1)
        if f is not None:
            vrow.addWidget(label("%s  %s" % (tr("col_factory"), p.fmt(f)), "Muted", th.font(9, 600)), 0, Qt.AlignBaseline)
        cl.addLayout(vrow)
        if p.options and raw is not None:
            cl.addWidget(label(p.option_text(raw) or "?", font=th.font(10, 600), wrap=True))

        if not p.ro:
            self.editor = ParamEditor(p)
            self.editor.set_raw(raw if raw is not None else f)
            cl.addWidget(self.editor)
            brow = QHBoxLayout()
            self.bt_write = btn(tr("write"), "primary")
            self.bt_write.clicked.connect(self.write_current)
            if self.editor.edit is not None:
                self.editor.edit.returnPressed.connect(self.write_current)
            brow.addWidget(self.bt_write, 1)
            if f is not None:
                bf = btn(tr("set_factory"), "small")
                bf.clicked.connect(lambda: self.editor.set_raw(f))
                brow.addWidget(bf)
            cl.addLayout(brow)
            why = self.write_block_reason(p)
            self.bt_write.setEnabled(not why)
            self.editor.setEnabled(not why)
            if why:
                w_ = label(why, wrap=True, font=th.font(9, 600))
                w_.setStyleSheet("color:%s;" % th.AMBER)
                cl.addWidget(w_)
        lay.addWidget(card)

        known = {x.code for x in self.ctx.cat.params if x.known}
        notes = []
        for key, d in self.ctx.fw.all_diffs(known).items():
            if p.code in d:
                kind, val = d[p.code]
                notes.append("BIOS %s: %s" % (key, {"added": tr("bios_added"), "missing": tr("bios_missing"),
                                                   "factory": tr("bios_factory", p.fmt(val))}[kind]))
        if notes:
            lay.addWidget(self.section("◆ BIOS", "<br>".join(notes), th.VIOLET))
        if p.range and not p.options:
            lay.addWidget(self.section(tr("range"), p.range))
        if p.options:
            html = "".join("<div style='margin:3px 0'><span style='color:%s;font-weight:700'>%d</span>"
                           "&nbsp;&nbsp;<span style='color:%s'>%s</span></div>"
                           % (th.ACCENT if n == raw else th.FAINT, n, th.TEXT if n == raw else th.MUTED, t)
                           for n, t in p.options)
            lay.addWidget(self.section(tr("options"), html))
        if p.help:
            body = "".join("<p style='margin:0 0 8px 0'>%s</p>" % ln.replace("<", "&lt;") for ln in p.help.splitlines())
            lay.addWidget(self.section(tr("description") + " · manual", body))
        lay.addStretch(1)
        self.detail.setWidget(w)

    def section(self, title: str, html: str, color: str = th.MUTED) -> QWidget:
        f = QFrame()
        f.setObjectName("Card")
        l = QVBoxLayout(f)
        l.setContentsMargins(16, 12, 16, 14)
        l.setSpacing(6)
        t = label(title.upper(), "CardTitle")
        t.setStyleSheet("color:%s;" % color)
        l.addWidget(t)
        tb = QLabel(html)
        tb.setTextFormat(Qt.RichText)
        tb.setWordWrap(True)
        tb.setFont(th.font(9.5))
        tb.setStyleSheet("color:%s;" % th.MUTED)
        tb.setTextInteractionFlags(Qt.TextSelectableByMouse)
        l.addWidget(tb)
        return f

    def write_block_reason(self, p: Param) -> str:
        if not self.ctx.connected:
            return tr("why_offline")
        key = self.ctx.identity.bios_key if self.ctx.identity else ""
        known = {x.code for x in self.ctx.cat.params if x.known}
        if self.ctx.fw.diff(key, known).get(p.code, ("",))[0] == "missing":
            return tr("why_missing_bios", key)
        if p.code in self.ctx.absent:
            return tr("why_absent")
        if p.stop_only and self.ctx.running:
            return tr("why_running")
        return ""

    # ---------------------------------------------------------------- read / write
    def update_enabled(self):
        on = self.ctx.connected
        self.bt_read.setEnabled(on and self.category.startswith("g"))
        self.bt_read_all.setEnabled(on)

    def read_current(self):
        if not self.ctx.connected:
            return
        if self.category.startswith("g"):
            codes = [p.code for p in self.ctx.cat.group(int(self.category[1:]))]
        else:
            codes = [p.code for p in self.model.rows]
        if codes and self.ctx.bus.start_job("setup:read", job_read, codes):
            self.lbl_prog.setText(tr("reading", ""))

    def read_all(self):
        if self.ctx.connected and self.ctx.bus.start_job("setup:read", job_read, [p.code for p in self.ctx.cat.params]):
            self.lbl_prog.setText(tr("reading", ""))

    def write_current(self):
        p = self.current
        if p is None or p.ro or not self.ctx.connected:
            return
        try:
            raw = self.editor.raw()
        except (ValueError, TypeError):
            self.lbl_prog.setText(tr("write_failed", p.code, "?"))
            return
        if p.stop_only and self.ctx.running:
            info(self, p.code, tr("running_warn"), warn=True)
            return
        if p.code in COMM_LINK and not ask(self, p.code, tr("comm_warn", p.code)):
            return
        if not p.known and not ask(self, p.code, tr("flag_unknown") + "\n\n" + tr("write") + "?"):
            return
        if not self.ctx.bus.start_job("setup:write", job_write, [WriteItem(p, raw)], p.stop_only):
            self.lbl_prog.setText(tr("busy"))

    def on_values(self, vals, why):
        self.ctx.values.update({k: v for k, v in vals.items() if v is not None})
        self.model.layoutChanged.emit()

    def on_progress(self, tag, done, total, text):
        if tag == "setup:read":
            self.lbl_prog.setText("%s  %d / %d" % (tr("reading", text), done, total))

    def on_done(self, tag, result):
        if tag == "setup:read":
            self.lbl_prog.setText("")
            self.ctx.values.update({k: v for k, v in result.items() if v is not None})
            self.refresh_counts()
            self.model.layoutChanged.emit()
            if self.current:
                self.show_detail(self.current)
        elif tag == "setup:write":
            for r in result:
                p = self.ctx.cat.get(r.code)
                if r.status in ("ok", "same"):
                    self.lbl_prog.setText("✓ " + tr("written", r.code, p.fmt(r.raw, True)))
                else:
                    self.lbl_prog.setText("✕ " + tr("write_failed", r.code, r.detail or r.status))
            self.refresh_counts()
            self.model.layoutChanged.emit()
            if self.current:
                self.show_detail(self.current)

    def on_failed(self, tag, err):
        if tag.startswith("setup:"):
            self.lbl_prog.setText("✕ " + err)

    def refresh_counts(self):
        for i in range(self.nav.count()):
            it = self.nav.item(i)
            if it.data(Qt.UserRole) == "changed":
                it.setData(Qt.UserRole + 3, self.count_changed())

    def done(self, r):
        self.strip.detach()
        for sig, fn in ((self.ctx.bus.values, self.on_values), (self.ctx.bus.job_progress, self.on_progress),
                        (self.ctx.bus.job_done, self.on_done), (self.ctx.bus.job_failed, self.on_failed)):
            try:
                sig.disconnect(fn)
            except (RuntimeError, TypeError):
                pass
        super().done(r)
