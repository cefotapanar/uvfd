# -*- coding: utf-8 -*-
"""
Main window: connection, drive identity (BIOS), live monitoring, start / stop
and the setpoint, the basic settings - and the buttons to Settings, Read and
Load at the top.
"""

from __future__ import annotations

import csv
import logging
import threading
import time
from datetime import datetime

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QMainWindow, QMenu, QProgressBar, QScrollArea, QSlider, QSpinBox,
                               QStackedWidget, QStatusBar, QVBoxLayout, QWidget)

from .. import drive as D
from .. import i18n, paths, updater
from ..bus import ConnectSpec, WriteItem, job_read, job_scan, job_write
from ..i18n import tr
from ..modbus import FORMATS, list_ports
from ..version import VERSION
from . import theme as th
from .common import Ctx, ParamEditor, ask, btn, chip, choose, info, label, set_prop
from .widgets import Banner, Bar, Card, Gauge, KpiTile, Led, StatusPill, Toggle, TrendChart, vsep

log = logging.getLogger("uvfd.ui")

# the drives' factory link first: PD-00 = 5 (9600), PD-01 = 0 (8N2)
BAUD_CHOICES = [9600, 19200, 38400, 4800, 2400, 1200, 57600, 115200, None]
FMT_CHOICES = [0, 1, 2, 3, None]
FMT_TEXT = {0: "8N2", 1: "8E1", 2: "8O1", 3: "8N1"}

BASIC_FIELDS = ["P0-02", "P0-03", "P0-10", "P0-12", "P0-14", "P0-17", "P0-18", "P6-10", "P8-13"]


class PortCombo(QComboBox):
    """The port list is read again every time it is opened - no refresh button needed."""

    def __init__(self, refresh):
        super().__init__()
        self._refresh = refresh

    def showPopup(self):
        self._refresh()
        super().showPopup()

    def paintEvent(self, e):
        from .common import ElidedCombo
        ElidedCombo.paintEvent(self, e)


class RowSnapScroll(QScrollArea):
    """Shows whole rows only - a list is never cut through a line of text."""

    def __init__(self, row_h: int):
        super().__init__()
        self.row_h = row_h

    def resizeEvent(self, e):
        rem = self.height() % self.row_h
        self.setViewportMargins(0, 0, 0, rem)
        super().resizeEvent(e)


class _UpdSignals(QObject):
    found = Signal(object)
    none = Signal(str)
    progress = Signal(int, int)
    ready = Signal(object)
    failed = Signal(str)


class MainWindow(QMainWindow):
    def __init__(self, ctx: Ctx, demo: str | None = None):
        super().__init__()
        self.ctx = ctx
        self.bus = ctx.bus
        self.start_demo = demo
        self.release = None
        self.rec_file = None
        self.rec_writer = None
        self.rec_rows = 0
        self.pending_bios_new = None
        self.dialog = None
        self.basic_dirty: set[str] = set()
        self.setWindowTitle("UVFD — Winston WSTG600 / SUSWE SU650")
        from .common import app_icon
        self.setWindowIcon(app_icon())
        self.setMinimumSize(1340, 780)

        b = self.bus
        b.connected.connect(self.on_connected)
        b.connect_failed.connect(self.on_connect_failed)
        b.connect_progress.connect(self.on_connect_progress)
        b.connect_cancelled.connect(self.on_connect_cancelled)
        b.disconnected.connect(self.on_disconnected)
        b.snapshot.connect(self.on_snapshot)
        b.values.connect(self.on_values)
        b.command_done.connect(self.on_command_done)
        b.link_state.connect(self.on_link_state)
        b.job_progress.connect(self.on_job_progress)
        b.job_done.connect(self.on_job_done)
        b.job_failed.connect(self.on_job_failed)

        self.upd = _UpdSignals()
        self.upd.found.connect(self.on_update_found)
        self.upd.none.connect(lambda v: self.toast(tr("no_update", v)) if self._manual_check else None)
        self.upd.failed.connect(lambda e: self.toast(tr("update_failed", e)) if self._manual_check else None)
        self._manual_check = False

        self.build()
        self.restore_geometry()

        sc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        sc.setContext(Qt.WindowShortcut)
        sc.activated.connect(self.do_stop)

        QTimer.singleShot(400, self.startup_checks)
        if demo:
            QTimer.singleShot(150, lambda: self.connect_now(demo_variant=demo))

    # ================================================================== build
    def build(self):
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self.build_topbar())

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(16, 14, 16, 14)
        bl.setSpacing(12)
        self.banner = Banner()
        bl.addWidget(self.banner)

        cols = QHBoxLayout()
        cols.setSpacing(14)
        cols.addWidget(self.build_control(), 0)
        cols.addLayout(self.build_middle(), 1)
        cols.addLayout(self.build_right(), 0)
        bl.addLayout(cols, 1)
        v.addWidget(body, 1)

        sb = QStatusBar()
        self.setStatusBar(sb)
        self.sb_msg = QLabel("")
        self.sb_stats = QLabel("")
        self.sb_hint = QLabel(tr("esc_stop"))
        self.sb_hint.setObjectName("Faint")
        sb.addWidget(self.sb_msg, 1)
        sb.addPermanentWidget(self.sb_stats)
        sb.addPermanentWidget(self.sb_hint)
        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self.update_stats)
        self._stats_timer.start(1000)

        self.refresh_ports()
        self.apply_connection_state()
        self.toast("")

    # ------------------------------------------------------------------ top bar
    def build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(64)
        h = QHBoxLayout(bar)
        h.setContentsMargins(18, 0, 14, 0)
        h.setSpacing(12)

        from .common import app_icon
        logo = QLabel()
        logo.setPixmap(app_icon(64).pixmap(32, 32))
        h.addWidget(logo)
        brand = QVBoxLayout()
        brand.setSpacing(0)
        t = label("UVFD", "Brand")
        t.setToolTip(tr("app_sub"))
        brand.addStretch(1)
        brand.addWidget(t)
        brand.addStretch(1)
        h.addLayout(brand)
        h.addSpacing(6)
        h.addWidget(vsep())
        h.addSpacing(4)

        # connection: full controls when offline, a summary when online
        self.conn_stack = QStackedWidget()
        off = QWidget()
        oh = QHBoxLayout(off)
        oh.setContentsMargins(0, 0, 0, 0)
        oh.setSpacing(8)
        self.cb_port = PortCombo(self.refresh_ports)
        self.cb_port.setFixedWidth(200)
        self.cb_port.setToolTip(tr("port"))
        self.cb_baud = QComboBox()
        for bd in BAUD_CHOICES:
            self.cb_baud.addItem(tr("auto") if bd is None else str(bd), bd)
            if bd == 9600:
                self.cb_baud.setItemData(self.cb_baud.count() - 1, "PD-00 = 5 · " + tr("factory_short"),
                                         Qt.ToolTipRole)
        self.cb_baud.setFixedWidth(96)
        self.cb_baud.setToolTip(tr("baud") + " (PD-00)")
        self.cb_fmt = QComboBox()
        for f in FMT_CHOICES:
            self.cb_fmt.addItem(tr("auto") if f is None else FMT_TEXT[f], f)
            if f is not None:
                self.cb_fmt.setItemData(self.cb_fmt.count() - 1, "PD-01 = %d%s" % (
                    f, " · " + tr("factory_short") if f == 0 else ""), Qt.ToolTipRole)
        self.cb_fmt.setFixedWidth(84)
        self.cb_fmt.setToolTip(tr("format") + " (PD-01)")
        self.sp_addr = QSpinBox()
        self.sp_addr.setRange(1, 247)
        self.sp_addr.setPrefix("#")
        self.sp_addr.setToolTip(tr("address") + " (PD-02)")
        self.sp_addr.setFixedWidth(62)
        st = self.ctx.settings
        self.sp_addr.setValue(int(st.get("slave") or 1))
        self.cb_baud.setCurrentIndex(max(0, self.cb_baud.findData(st.get("baud"))))
        self.cb_fmt.setCurrentIndex(max(0, self.cb_fmt.findData(st.get("fmt"))))
        self.bt_connect = btn(tr("connect"), "primary")
        self.bt_connect.setMinimumWidth(104)
        self.bt_connect.clicked.connect(lambda: self.connect_now())
        self.bt_help = btn("?  " + tr("help_short"), "small", tr("conn_help"))
        self.bt_help.clicked.connect(self.open_connect_help)
        for w in (self.cb_port, self.cb_baud, self.cb_fmt, self.sp_addr, self.bt_connect, self.bt_help):
            oh.addWidget(w)
        oh.addStretch(1)
        self.conn_stack.addWidget(off)

        on = QWidget()
        nh = QHBoxLayout(on)
        nh.setContentsMargins(0, 0, 0, 0)
        nh.setSpacing(10)
        self.dot = QLabel("●")
        self.dot.setStyleSheet("color:%s; font-size:13pt;" % th.ACCENT)
        nh.addWidget(self.dot)
        lt = QVBoxLayout()
        lt.setSpacing(0)
        self.lbl_link = label("", font=th.font(9.5, 600))
        self.lbl_link2 = label("", "Muted", th.font(8.5, 500))
        lt.addStretch(1)
        lt.addWidget(self.lbl_link)
        lt.addWidget(self.lbl_link2)
        lt.addStretch(1)
        nh.addLayout(lt)
        nh.addSpacing(8)
        self.bios_box = QHBoxLayout()
        self.bios_box.setSpacing(6)
        nh.addLayout(self.bios_box)
        self.bt_disconnect = btn(tr("disconnect"), "small")
        self.bt_disconnect.clicked.connect(self.disconnect_now)
        nh.addSpacing(6)
        nh.addWidget(self.bt_disconnect)
        nh.addStretch(1)
        self.conn_stack.addWidget(on)
        h.addWidget(self.conn_stack)
        h.addStretch(1)

        self.bt_update = btn("", "update")
        self.bt_update.hide()
        self.bt_update.clicked.connect(self.show_update)
        h.addWidget(self.bt_update)

        self.bt_settings = btn("⚙  " + tr("settings"), "nav")
        self.bt_settings.clicked.connect(self.open_setup)
        self.bt_read = btn("⤓  " + tr("read"), "nav", tr("read_tip"))
        self.bt_read.clicked.connect(self.do_read_all)
        self.bt_load = btn("⤒  " + tr("load"), "nav", tr("load_tip"))
        self.bt_load.clicked.connect(self.open_snapshots)
        for w in (self.bt_settings, self.bt_read, self.bt_load):
            h.addWidget(w)
        h.addSpacing(4)
        h.addWidget(vsep())

        lang = QHBoxLayout()
        lang.setSpacing(2)
        self.bt_mk = btn("MK", "lang", tr("lang_tip"))
        self.bt_en = btn("EN", "lang", tr("lang_tip"))
        for b_, code in ((self.bt_mk, "mk"), (self.bt_en, "en")):
            b_.setCheckable(True)
            b_.setChecked(i18n.lang() == code)
            b_.clicked.connect(lambda _=False, c=code: self.switch_lang(c))
            lang.addWidget(b_)
        h.addLayout(lang)

        self.bt_menu = btn("☰", "ghost")
        self.bt_menu.setFixedWidth(38)
        m = QMenu(self)
        m.addAction(tr("conn_help"), self.open_connect_help)
        m.addAction(tr("bios_window"), self.open_bios)
        m.addAction(tr("prefs"), self.open_prefs)
        m.addSeparator()
        m.addAction(tr("check_updates"), lambda: self.check_updates(manual=True))
        m.addAction(tr("about"), self.about)
        self.bt_menu.setMenu(m)
        self.bt_menu.setStyleSheet("QPushButton::menu-indicator { image: none; width: 0; }")
        h.addWidget(self.bt_menu)
        return bar

    # ------------------------------------------------------------------ control column
    def build_control(self) -> QWidget:
        card = Card(tr("control"))
        card.setFixedWidth(372)
        lay = card.lay
        self.pill = StatusPill()
        lay.addWidget(self.pill)
        self.gauge = Gauge()
        lay.addWidget(self.gauge, 1)

        # setpoint
        sp = QFrame()
        sp.setObjectName("Card")
        sp.setStyleSheet("#Card { background:%s; border-radius:12px; }" % th.SURFACE2)
        sv = QVBoxLayout(sp)
        sv.setContentsMargins(12, 10, 12, 12)
        sv.setSpacing(8)
        top = QHBoxLayout()
        self.lbl_sp = label(tr("set_hz").upper(), "CardTitle")
        top.addWidget(self.lbl_sp)
        top.addStretch(1)
        self.sp_hz = QDoubleSpinBox()
        self.sp_hz.setDecimals(2)
        self.sp_hz.setSuffix(" Hz")
        self.sp_hz.setRange(0, 50)
        self.sp_hz.setAlignment(Qt.AlignRight)
        self.sp_hz.setFont(th.font(12, 700, tabular=True))
        self.sp_hz.setFixedWidth(120)
        self.sp_hz.setKeyboardTracking(False)
        self.sp_hz.valueChanged.connect(self.on_spin_hz)
        top.addWidget(self.sp_hz)
        sv.addLayout(top)
        self.sl_hz = QSlider(Qt.Horizontal)
        self.sl_hz.setRange(0, 5000)
        self.sl_hz.valueChanged.connect(self.on_slider_hz)
        self.sl_hz.sliderReleased.connect(lambda: self.send_hz(self.sl_hz.value() / 100.0))
        sv.addWidget(self.sl_hz)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        self.preset_btns = []
        for hz in self.ctx.settings.get("preset_hz") or [10, 25, 35, 50]:
            b_ = btn("%g Hz" % hz, "chip")
            b_.clicked.connect(lambda _=False, v=hz: self.preset(v))
            chips.addWidget(b_, 1)
            self.preset_btns.append(b_)
        sv.addLayout(chips)
        lay.addWidget(sp)

        g = QGridLayout()
        g.setSpacing(8)
        self.bt_fwd = btn("▶  " + tr("fwd"), "run")
        self.bt_rev = btn("◀  " + tr("rev"), "run")
        self.bt_fwd.clicked.connect(lambda: self.do_run(D.CMD_FWD))
        self.bt_rev.clicked.connect(lambda: self.do_run(D.CMD_REV))
        self.bt_stop = btn("■  " + tr("stop"), "stop")
        self.bt_stop.clicked.connect(self.do_stop)
        self.bt_jog = btn(tr("jog"), "small")
        self.bt_jog.pressed.connect(lambda: self.bus.command(D.CMD_JOG_FWD))
        self.bt_jog.released.connect(lambda: self.bus.command(D.CMD_STOP))
        self.bt_coast = btn(tr("coast"), "small")
        self.bt_coast.clicked.connect(lambda: self.bus.command(D.CMD_COAST))
        self.bt_reset = btn(tr("reset"), "small")
        self.bt_reset.clicked.connect(lambda: self.bus.command(D.CMD_RESET))
        g.addWidget(self.bt_rev, 0, 0)
        g.addWidget(self.bt_fwd, 0, 1)
        g.addWidget(self.bt_stop, 1, 0, 1, 2)
        small = QHBoxLayout()
        small.setSpacing(6)
        for w in (self.bt_jog, self.bt_coast, self.bt_reset):
            small.addWidget(w)
        g.addLayout(small, 2, 0, 1, 2)
        lay.addLayout(g)

        pc = QHBoxLayout()
        pc.setSpacing(10)
        self.tg_pc = Toggle()
        self.tg_pc.toggled.connect(self.on_pc_toggle)
        pc.addWidget(self.tg_pc)
        pcl = QVBoxLayout()
        pcl.setSpacing(0)
        self.lbl_pc = label(tr("pc_control"), font=th.font(10, 700))
        self.lbl_pc2 = label("", "Muted", th.font(8.5), wrap=True)
        pcl.addWidget(self.lbl_pc)
        pcl.addWidget(self.lbl_pc2)
        pc.addLayout(pcl, 1)
        lay.addLayout(pc)
        return card

    # ------------------------------------------------------------------ middle
    def build_middle(self):
        col = QVBoxLayout()
        col.setSpacing(12)
        grid = QGridLayout()
        grid.setSpacing(12)
        spec = [
            ("out_a", tr("kpi_current"), "A", th.ACCENT, 2),
            ("out_v", tr("kpi_voltage"), "V", th.BLUE, 0),
            ("dc_bus", tr("kpi_bus"), "V", th.VIOLET, 1),
            ("out_kw", tr("kpi_power"), "kW", th.AMBER, 1),
            ("torque", tr("kpi_torque"), "%", th.ACCENT, 1),
            ("rpm", tr("kpi_speed"), "rpm", th.BLUE, 0),
            ("temp", tr("kpi_temp"), "°C", th.AMBER, 0),
            ("set_hz", tr("kpi_set"), "Hz", th.VIOLET, 2),
        ]
        self.kpi = {}
        for n, (key, title, unit, color, dec) in enumerate(spec):
            t = KpiTile(title, unit, color, dec)
            self.kpi[key] = t
            grid.addWidget(t, n // 4, n % 4)
        col.addLayout(grid)

        tc = Card(tr("trend"))
        self.bt_rec = btn("●  " + tr("record"), "small")
        self.bt_rec.clicked.connect(self.toggle_record)
        tc.head.addWidget(self.bt_rec)
        self.trend = TrendChart(120)
        self.trend.add_series("hz", tr("out_freq"), "Hz", th.ACCENT)
        self.trend.add_series("a", D.MON_BY_KEY["out_a"].title(i18n.lang()), "A", th.BLUE)
        self.trend.add_series("kw", D.MON_BY_KEY["out_kw"].title(i18n.lang()), "kW", th.AMBER)
        tc.lay.addWidget(self.trend, 1)
        col.addWidget(tc, 1)

        row = QHBoxLayout()
        row.setSpacing(12)
        io = Card(tr("io"))
        ig = QGridLayout()
        ig.setHorizontalSpacing(2)
        ig.setVerticalSpacing(8)
        self.di_leds = [Led(n, th.ACCENT) for n in D.DI_BITS]
        self.do_leds = [Led(n, th.AMBER) for n in D.DO_BITS]
        for k, l_ in enumerate(self.di_leds):
            ig.addWidget(l_, 0, k)
        for k, l_ in enumerate(self.do_leds):
            ig.addWidget(l_, 1, k)
        io.lay.addLayout(ig)
        self.ai_bars = {"ai1": Bar("AI1"), "ai2": Bar("AI2"), "pot_raw": Bar("AI3")}
        for b_ in self.ai_bars.values():
            io.lay.addWidget(b_)
        row.addWidget(io, 1)

        cc = Card(tr("counters"))
        cg = QGridLayout()
        cg.setHorizontalSpacing(14)
        cg.setVerticalSpacing(6)
        self.cnt = {}
        for r, (key, title, unit) in enumerate((("P7-09", tr("run_hours"), "h"), ("P7-13", tr("on_hours"), "h"),
                                                ("P7-14", tr("energy"), "kWh"))):
            cg.addWidget(label(title, "Muted", th.font(9)), r, 0)
            v_ = label("—", font=th.font(11, 700, tabular=True))
            v_.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.cnt[key] = (v_, unit)
            cg.addWidget(v_, r, 1)
        cc.lay.addLayout(cg)
        cc.lay.addWidget(label(tr("last_faults").upper(), "CardTitle"))
        self.lbl_faults = label("—", font=th.font(9), wrap=True)
        self.lbl_faults.setTextFormat(Qt.RichText)
        cc.lay.addWidget(self.lbl_faults)
        cc.lay.addStretch(1)
        row.addWidget(cc, 1)
        col.addLayout(row)
        return col

    # ------------------------------------------------------------------ right column
    def build_right(self):
        col = QVBoxLayout()
        col.setSpacing(12)
        bc = Card(tr("basics"))
        bc.setFixedWidth(360)
        self.bt_factory = btn("↺  " + tr("factory_btn"), "small", tr("factory_btn_tip"))
        self.bt_factory.clicked.connect(self.open_factory_reset)
        bc.head.addWidget(self.bt_factory)
        bg = QGridLayout()
        bg.setHorizontalSpacing(8)
        bg.setVerticalSpacing(7)
        self.basic_editors = {}
        self.basic_write = {}
        for r, code in enumerate(BASIC_FIELDS):
            p = self.ctx.cat.get(code)
            name = QLabel()
            name.setText("<span style='color:%s;font-weight:700'>%s</span><br><span style='color:%s'>%s</span>"
                         % (th.FAINT, code, th.MUTED, p.name))
            name.setFont(th.font(8.5))
            name.setTextFormat(Qt.RichText)
            name.setFixedWidth(142)
            name.setWordWrap(True)
            name.setToolTip(p.name)
            ed = ParamEditor(p, compact=True)
            ed.setFixedWidth(160)
            ed.on_change(lambda c=code: self.mark_basic_dirty(c))
            if ed.edit is not None:
                ed.edit.returnPressed.connect(lambda c=code: self.write_basic(c))
            wb = btn("✓", "small")
            wb.setFixedWidth(30)
            wb.setToolTip(tr("write"))
            wb.clicked.connect(lambda _=False, c=code: self.write_basic(c))
            wb.setVisible(False)
            bg.addWidget(name, r, 0)
            bg.addWidget(ed, r, 1)
            bg.addWidget(wb, r, 2)
            self.basic_editors[code] = ed
            self.basic_write[code] = wb
        bc.lay.addLayout(bg)
        col.addWidget(bc)

        mc = Card()
        mc.setFixedWidth(360)
        from PySide6.QtWidgets import QTabWidget
        from .drive_panel import DrivePanel
        self.right_tabs = QTabWidget()
        self.right_tabs.setDocumentMode(True)
        self.drive_panel = DrivePanel(self.ctx, self.edit_model_label)
        self.right_tabs.addTab(self.drive_panel, tr("drive_tab"))
        area = RowSnapScroll(23)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        mg = QGridLayout(inner)
        mg.setContentsMargins(0, 0, 6, 0)
        mg.setHorizontalSpacing(10)
        mg.setVerticalSpacing(0)
        self.mon_labels = {}
        shown = {"run_hz", "out_a", "out_v", "dc_bus", "out_kw", "torque", "temp", "set_hz", "di", "do"}
        r = 0
        for m in D.MONITOR:
            if m.key in shown:
                continue
            name_ = label(m.title(i18n.lang()), "Muted", th.font(9))
            name_.setFixedHeight(23)
            mg.addWidget(name_, r, 0)
            v_ = label("—", font=th.font(9.5, 600, tabular=True))
            v_.setFixedHeight(23)
            v_.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            mg.addWidget(v_, r, 1)
            self.mon_labels[m.idx] = v_
            r += 1
        mg.setRowStretch(r, 1)
        area.setWidget(inner)
        self.right_tabs.addTab(area, tr("all_live"))
        mc.lay.addWidget(self.right_tabs, 1)
        col.addWidget(mc, 1)
        return col

    # ================================================================== connection
    def refresh_ports(self):
        cur = self.cb_port.currentData() or self.ctx.settings.get("port")
        self.cb_port.blockSignals(True)
        self.cb_port.clear()
        for dev, desc in list_ports():
            short = desc.replace("(%s)" % dev, "").strip()
            self.cb_port.addItem("%s  ·  %s" % (dev, short[:22]) if short else dev, dev)
        self.cb_port.addItem(tr("demo") + "  · BIOS 21", "DEMO:21")
        self.cb_port.addItem(tr("demo") + "  · BIOS 502", "DEMO:502")
        i = self.cb_port.findData(cur)
        self.cb_port.setCurrentIndex(i if i >= 0 else 0)
        self.cb_port.blockSignals(False)

    def connect_now(self, demo_variant: str | None = None, scan: bool = False):
        port = "DEMO:" + demo_variant if demo_variant else self.cb_port.currentData()
        if not port:
            return
        demo = port.split(":", 1)[1] if port.startswith("DEMO:") else None
        st = self.ctx.settings
        if demo_variant:
            i = self.cb_port.findData(port)
            if i >= 0:
                self.cb_port.setCurrentIndex(i)
        st["port"] = port
        st["baud"] = self.cb_baud.currentData()
        st["fmt"] = self.cb_fmt.currentData()
        st["slave"] = self.sp_addr.value()
        st.save()
        self.bt_connect.setEnabled(False)
        self.bt_connect.setText(tr("connecting"))
        self.bus.fast_ms = int(st.get("poll_ms") or 250)
        self.bus.connect_drive(ConnectSpec(port=port, baud=st["baud"], fmt=st["fmt"], slave=st["slave"],
                                           demo=demo, comm_timeout=float(st.get("comm_timeout") or 0),
                                           scan=scan))
        if scan:
            from .dialogs import ProgressDialog
            self.scan_dlg = ProgressDialog(self, tr("searching", self.cb_port.currentText().split("·")[0].strip()),
                                           self.bus, cancel=self.bus.cancel_connect)
            self.scan_dlg.show()

    def search_drive(self):
        self.connect_now(scan=True)

    def factory_link(self):
        self.cb_baud.setCurrentIndex(self.cb_baud.findData(9600))
        self.cb_fmt.setCurrentIndex(self.cb_fmt.findData(0))
        self.sp_addr.setValue(1)
        self.toast(tr("factory_link"))

    def open_connect_help(self):
        from .connect_help import ConnectHelpDialog
        on = self.ctx.connected
        ConnectHelpDialog(self, on_search=None if on else self.search_drive,
                          on_factory=None if on else self.factory_link).exec()

    def close_scan(self):
        d = getattr(self, "scan_dlg", None)
        if d is not None:
            d.finish()
            self.scan_dlg = None

    def on_connect_progress(self, what: str, n: int, total: int):
        d = getattr(self, "scan_dlg", None)
        if d is not None:
            d.set_progress(n, total, what)
        else:
            self.toast(tr("trying", what, n, total))

    def disconnect_now(self):
        self.leave(then=lambda: self.bus.disconnect_drive(True), closing=False)

    # ------------------------------------------------------------------ leaving a drive
    def drive_tag(self) -> dict:
        """Which drive this is: the PC-control memory belongs to one drive only."""
        st = self.ctx.settings
        return {"port": st.get("port", ""), "slave": int(st.get("slave") or 1)}

    def pc_ours(self) -> bool:
        """PC control is on AND it was UVFD that turned it on, on this very drive."""
        r = self.ctx.settings.get("pc_restore") or {}
        if not (self.pc_active() and r.get("P0-02") is not None):
            return False
        tag = self.drive_tag()
        return all(r.get(k, tag[k]) == tag[k] for k in tag)      # older entries carry no tag

    def restore_values(self) -> dict:
        r = dict(self.ctx.settings.get("pc_restore") or {})
        out = {"P0-02": r.get("P0-02"), "P0-03": r.get("P0-03")}
        if out["P0-02"] in (None, D.P002_COMM):
            out["P0-02"] = D.P002_PANEL
        if out["P0-03"] in (None, D.P003_COMM):
            out["P0-03"] = self.ctx.cat.get("P0-03").default or 0
        return out

    def leave(self, then, closing: bool):
        """
        Before disconnecting / closing. Asks to restore the previous mode only
        when UVFD itself switched this drive to PC control; otherwise only a
        running motor is asked about, as before.
        """
        if not self.ctx.connected:
            then()
            return
        if self.pc_ours():
            rv = self.restore_values()
            p2, p3 = self.ctx.cat.get("P0-02"), self.ctx.cat.get("P0-03")
            text = tr("pc_restore_q", "%d · %s" % (rv["P0-02"], p2.option_text(rv["P0-02"])),
                      "%d · %s" % (rv["P0-03"], p3.option_text(rv["P0-03"])))
            if self.ctx.running:
                text += tr("pc_restore_q_run")
            answer = choose(self, tr("disconnect"), text,
                            [tr("pc_restore_yes"), tr("pc_restore_no"), tr("cancel")])
            if answer == 0:
                self.restore_mode(then=then)
                return
            if answer != 1:
                return
        if self.ctx.running and self.pc_active():
            options = [tr("exit_stop"), tr("exit_leave"), tr("cancel")] if closing else [tr("exit_stop"), tr("cancel")]
            answer = choose(self, tr("disconnect"), tr("exit_running"), options)
            if answer == 0:
                self.bus.command(D.CMD_STOP)
                QTimer.singleShot(300, then)
            elif closing and answer == 1:
                then()
            return
        then()

    def restore_mode(self, then):
        """Stop if needed (P0-03 changes only when stopped), write the old P0-02/P0-03, then `then`."""
        rv = self.restore_values()

        def write():
            def done(ok, err):
                if ok:
                    self.ctx.settings["pc_restore"] = {}
                    self.ctx.settings.save()
                    self.toast(tr("pc_restored", rv["P0-02"], rv["P0-03"]))
                    if then is not None:
                        then()
                else:
                    self.toast("%s: %s" % (tr("error"), err), error=True)
            self._after_pc = done
            self.bus.pc_control(False, rv)

        if not self.ctx.running:
            write()
            return
        self.bus.command(D.CMD_STOP)
        self.toast(tr("waiting_stop"))
        t0 = time.monotonic()

        def wait():
            if not self.ctx.connected:
                return
            if self.ctx.status == D.ST_STOP:
                write()
            elif time.monotonic() - t0 > 120:
                self.toast(tr("stop_timeout"), error=True)
            else:
                QTimer.singleShot(200, wait)
        QTimer.singleShot(200, wait)

    def on_connected(self, info_: dict):
        ident: D.Identity = info_["identity"]
        self.ctx.identity = ident
        self.ctx.values.update({k: v for k, v in info_["values"].items() if v is not None})
        self.ctx.link_text = info_["link"]
        self.ctx.absent.clear()
        self.ctx.demo = info_.get("demo")
        self.close_scan()
        st = self.ctx.settings
        st["baud"], st["fmt"], st["slave"] = info_["baud"], info_["fmt"], info_.get("slave", st.get("slave", 1))
        st.save()
        for cb, val in ((self.cb_baud, st["baud"]), (self.cb_fmt, st["fmt"])):
            i = cb.findData(val)
            if i >= 0:
                cb.setCurrentIndex(i)
        self.sp_addr.setValue(int(st["slave"]))
        new = self.ctx.fw.seen(ident.bios_key, ident.model_text)
        self.bt_connect.setEnabled(True)
        self.bt_connect.setText(tr("connect"))
        for t in self.kpi.values():
            t.reset()
        self.trend.clear()
        self.apply_connection_state()
        self.apply_values(info_["values"])
        self.sync_setpoint_range()
        sp = self.ctx.values.get("P0-08")
        self.toast(tr("connected") + " — " + self.ctx.link_display())
        if new:
            first = self.ctx.fw.base == ident.bios_key
            text = tr("bios_first_banner", ident.bios_key) if first else \
                tr("bios_new_banner", ident.bios_key, self.ctx.fw.base)
            b_ = btn(tr("scan"), "small")
            b_.clicked.connect(self.scan_bios)
            self.banner.show_msg(text, th.VIOLET, "◆", [b_])
        else:
            self.banner.hide_msg()

    def on_connect_cancelled(self):
        self.close_scan()
        self.bt_connect.setEnabled(True)
        self.bt_connect.setText(tr("connect"))
        self.toast(tr("search_cancelled"))

    def on_connect_failed(self, msg: str):
        self.close_scan()
        self.bt_connect.setEnabled(True)
        self.bt_connect.setText(tr("connect"))
        b_help = btn(tr("help_short"), "small")
        b_help.clicked.connect(self.open_connect_help)
        b_find = btn(tr("find_drive"), "small")
        b_find.clicked.connect(self.search_drive)
        self.banner.show_msg(msg, th.RED, "✕", [b_find, b_help])

    def on_disconnected(self, _msg: str):
        self.ctx.identity = None
        self.ctx.status = -1
        self.stop_record()
        self.apply_connection_state()
        self.toast(tr("not_connected"))

    def apply_connection_state(self):
        on = self.bus.is_connected and self.ctx.identity is not None
        self.conn_stack.setCurrentIndex(1 if on else 0)
        for w in (self.bt_read,):
            w.setEnabled(on)
        if on:
            ident = self.ctx.identity
            self.lbl_link.setText(self.ctx.link_display())
            from .drive_panel import label_summary
            lab = label_summary(self.ctx.fw.model_label(ident.model))
            parts = [lab or "%s %s" % (tr("model_no"), ident.model_text)]
            if ident.gp in (1, 2):
                parts.append("G" if ident.gp == 1 else "P")
            self.lbl_link2.setText("  ·  ".join(parts))
            while self.bios_box.count():
                it = self.bios_box.takeAt(0)
                if it.widget():
                    it.widget().deleteLater()
            key = ident.bios_key
            b_ = btn("◆  BIOS %s" % key, "small")
            b_.setStyleSheet("QPushButton { color:%s; border-color:%s; background:%s; }"
                             % (th.VIOLET, th.rgba(th.VIOLET, 110),
                                th.rgba(th.VIOLET, 28)))
            b_.clicked.connect(self.open_bios)
            self.bios_box.addWidget(b_)
            if key == self.ctx.fw.base:
                self.bios_box.addWidget(chip(tr("bios_base"), th.VIOLET), 0, Qt.AlignVCenter)
            elif self.ctx.fw.versions.get(key, {}).get("seen", 0) <= 1:
                self.bios_box.addWidget(chip(tr("bios_new"), th.AMBER, filled=True), 0, Qt.AlignVCenter)
        else:
            self.pill.set_state(tr("st_offline"), th.FAINT, False)
            self.gauge.set_value(0, None)
            self.gauge.sub = ""
            self.gauge.fault = False
        self.drive_panel.refresh()
        self.update_controls()

    # ================================================================== live data
    def on_snapshot(self, s: D.Snapshot):
        lang = i18n.lang()
        u = s.u0
        if s.status != -2:                      # fast poll
            if not s.ok:
                return
            self.ctx.status = s.status
            fault_changed = s.fault != self.ctx.fault
            self.ctx.fault = s.fault
            if fault_changed:
                self.apply_values({})
                self.bus.totals_at = 0          # the drive's fault history changes with it
            cur_dec = 1 if self.ctx.values.get("PD-06") == 1 else 2

            def val(key):
                m = D.MON_BY_KEY[key]
                raw = u.get(m.idx)
                if raw is None:
                    return None
                if m.signed and raw > 32767:
                    raw -= 65536
                dec = cur_dec if key == "out_a" else m.dec
                return raw / (10 ** dec)

            hz = val("run_hz")
            set_hz = val("set_hz")
            self.gauge.set_value(hz, set_hz, self.bus.max_hz)
            self.gauge.sub = ("%s %.2f Hz" % (tr("setpoint"), set_hz)) if set_hz is not None else ""
            self.gauge.fault = bool(s.fault)
            for key in ("out_a", "out_v", "dc_bus", "out_kw", "torque", "temp", "set_hz"):
                self.kpi[key].set_value(val(key))
            self.drive_panel.set_dc(val("dc_bus"))
            rated_hz = (self.ctx.values.get("P1-04") or 5000) / 100.0
            rated_rpm = self.ctx.values.get("P1-05") or 1450
            if hz is not None and rated_hz > 0:
                rpm = hz / rated_hz * rated_rpm
                self.kpi["rpm"].set_value(rpm, "%.0f" % rpm)
            now = time.time()
            self.trend.push("hz", now, hz)
            self.trend.push("a", now, val("out_a"))
            self.trend.push("kw", now, val("out_kw"))
            self.trend.update()
            di, do = u.get(7), u.get(8)
            for k, l_ in enumerate(self.di_leds):
                l_.set_on(bool(di is not None and di >> k & 1))
            for k, l_ in enumerate(self.do_leds):
                l_.set_on(bool(do is not None and do >> k & 1))
            for key in ("ai1", "ai2"):
                self.ai_bars[key].set_value(val(key))
            # status
            if s.fault:
                self.pill.set_state("%s  %s" % (tr("st_fault"), D.fault_code_label(s.fault)), th.RED, True, solid=True)
                text = tr("fault_banner", D.fault_code_label(s.fault), D.fault_text(s.fault, lang))
                if self.banner.text.text() != text:
                    b_ = btn(tr("reset"), "small")
                    b_.setStyleSheet("QPushButton { background:#FFFFFF; color:#9B1C2C; border:0; padding:7px 14px; }"
                                     "QPushButton:hover { background:#FFE3E7; }")
                    b_.clicked.connect(lambda: self.bus.command(D.CMD_RESET))
                    self.banner.show_msg(text, "#C8323C", "⚠", [b_], solid=True)
            else:
                if self.banner.kind == "⚠":
                    self.banner.hide_msg("⚠")
                    self.toast("")
                if s.status == D.ST_FWD:
                    self.pill.set_state(tr("st_run_fwd"), th.ACCENT, True)
                elif s.status == D.ST_REV:
                    self.pill.set_state(tr("st_run_rev"), th.ACCENT, True)
                else:
                    self.pill.set_state(tr("st_stop"), th.MUTED, False)
            self.update_controls()
            self.record_row(s, val)
        # slow and fast both feed the measurement list
        for idx, lab in self.mon_labels.items():
            if idx in u:
                m = D.MON_BY_IDX[idx]
                raw = u[idx]
                if m.signed and raw > 32767:
                    raw -= 65536
                lab.setText(("%.*f" % (m.dec, raw / 10 ** m.dec) if m.dec else str(raw))
                            + (" " + m.unit if m.unit else ""))
        if 23 in u:
            raw = u[23] - 65536 if u[23] > 32767 else u[23]
            self.ai_bars["pot_raw"].set_value(raw / 1000.0)

    def on_values(self, vals: dict, why: str):
        self.ctx.values.update({k: v for k, v in vals.items() if v is not None})
        if why == "read":
            self.ctx.absent.update(k for k, v in vals.items() if v is None)
            self.ctx.absent.difference_update(k for k, v in vals.items() if v is not None)
        self.apply_values(vals)

    def apply_values(self, vals: dict):
        for code, ed in self.basic_editors.items():
            if code in vals and vals[code] is not None and code not in self.basic_dirty:
                ed.set_raw(vals[code])
        for code, (lab, unit) in self.cnt.items():
            v = self.ctx.values.get(code)
            if v is not None:
                lab.setText("%s %s" % (format(v, ",").replace(",", " "), unit))
        faults = [self.ctx.values.get(c) for c in ("P9-14", "P9-15", "P9-16")]
        if any(f is not None for f in faults) or self.ctx.fault:
            lines = []
            if self.ctx.fault:
                lines.append("<span style='color:%s;font-weight:800'>● %s  %s</span>"
                             % (th.RED, D.fault_code_label(self.ctx.fault), D.fault_text(self.ctx.fault, i18n.lang())))
            for n, f in enumerate(faults):
                if f is None:
                    continue
                col = th.FAINT if f == 0 else (th.AMBER if n else th.RED)
                lines.append("<span style='color:%s;font-weight:700'>%d.</span> "
                             "<span style='color:%s'>%s</span> %s"
                             % (th.FAINT, n + 1, col, D.fault_code_label(f) if f else "—",
                                D.fault_text(f, i18n.lang()) if f else ""))
            self.lbl_faults.setText("<br>".join(lines))
        if any(c in vals for c in ("P0-10", "P0-22")):
            self.sync_setpoint_range()
        self.drive_panel.refresh()
        self.update_controls()

    # ================================================================== control
    def pc_active(self) -> bool:
        return self.ctx.values.get("P0-02") == D.P002_COMM

    def src_name(self) -> str:
        v = self.ctx.values.get("P0-02")
        return {0: tr("src_panel"), 1: tr("src_terminal"), 2: tr("src_comm")}.get(v, "?")

    def update_controls(self):
        on = self.bus.is_connected and self.ctx.identity is not None
        pc = on and self.pc_active()
        fault = bool(self.ctx.fault)
        running = self.ctx.running
        for b_ in (self.bt_fwd, self.bt_rev, self.bt_jog):
            b_.setEnabled(pc and not fault)
        self.bt_stop.setEnabled(on)
        self.bt_coast.setEnabled(on)
        self.bt_reset.setEnabled(on and fault)
        hz_ok = pc and self.ctx.values.get("P0-03") == D.P003_COMM
        for w in [self.sp_hz, self.sl_hz] + self.preset_btns:
            w.setEnabled(hz_ok)
        set_prop(self.bt_fwd, "active", "true" if self.ctx.status == D.ST_FWD else "false")
        set_prop(self.bt_rev, "active", "true" if self.ctx.status == D.ST_REV else "false")
        self.tg_pc.setEnabled(on and not (running and pc))
        if self.tg_pc.checked != pc:
            self.tg_pc.set_checked(pc)
        if not on:
            self.lbl_pc2.setText(tr("connect_first"))
        elif pc:
            t = self.ctx.values.get("PD-04")
            self.lbl_pc2.setText("P0-02 = 2 · P0-03 = %s · PD-04 = %s s"
                                 % (self.ctx.values.get("P0-03", "?"), "%.1f" % (t / 10) if t is not None else "?"))
        else:
            self.lbl_pc2.setText(tr("pc_off_hint", self.src_name()))
        self.bt_read.setEnabled(on)
        self.bt_factory.setEnabled(on and not running)
        for code, ed in self.basic_editors.items():
            ed.setEnabled(on)

    def sync_setpoint_range(self):
        mx = max(1.0, self.bus.max_hz)
        self.sp_hz.blockSignals(True)
        self.sl_hz.blockSignals(True)
        self.sp_hz.setRange(0, mx)
        self.sl_hz.setRange(0, int(round(mx * 100)))
        self.sp_hz.setValue(self.bus.setpoint_hz)
        self.sl_hz.setValue(int(round(self.bus.setpoint_hz * 100)))
        self.sp_hz.blockSignals(False)
        self.sl_hz.blockSignals(False)
        self.gauge.maximum = mx

    def on_slider_hz(self, v: int):
        self.sp_hz.blockSignals(True)
        self.sp_hz.setValue(v / 100.0)
        self.sp_hz.blockSignals(False)
        now = time.monotonic()
        if now - getattr(self, "_last_hz_send", 0) > 0.15:
            self._last_hz_send = now
            self.send_hz(v / 100.0)

    def on_spin_hz(self, v: float):
        self.sl_hz.blockSignals(True)
        self.sl_hz.setValue(int(round(v * 100)))
        self.sl_hz.blockSignals(False)
        self.send_hz(v)

    def preset(self, hz: float):
        hz = min(hz, self.bus.max_hz)
        self.sp_hz.setValue(hz)

    def send_hz(self, hz: float):
        if self.bus.is_connected:
            self.bus.set_frequency(hz)

    def do_run(self, cmd: int):
        if not self.pc_active():
            return
        self.send_hz(self.sp_hz.value())
        self.bus.command(cmd)

    def do_stop(self):
        if self.bus.is_connected:
            self.bus.command(D.CMD_STOP)

    def on_pc_toggle(self, want: bool):
        if not self.ctx.connected:
            return
        st = self.ctx.settings
        t = float(st.get("comm_timeout") or 0)
        if want:
            if not ask(self, tr("pc_control"), tr("pc_confirm", t, t), tr("pc_enable")):
                return
            st["pc_restore"] = {"P0-02": self.ctx.values.get("P0-02"), "P0-03": self.ctx.values.get("P0-03"),
                                **self.drive_tag()}
            st.save()
            self.bus.pc_control(True)
        else:
            if self.ctx.running:
                info(self, tr("pc_control"), tr("need_stop"), warn=True)
                return
            self.restore_mode(then=None)

    def on_command_done(self, what: str, ok: bool, err: str):
        if what == "pc":
            cb, self._after_pc = getattr(self, "_after_pc", None), None
            if cb is not None:
                cb(ok, err)
        if not ok and what == "pd04":
            self.banner.show_msg(err, th.AMBER, "⚠")
            return
        if not ok:
            self.toast("%s: %s" % (tr("error"), err), error=True)

    def on_link_state(self, ok: bool):
        if ok:
            self.banner.hide_msg("⇄")
        else:
            self.banner.show_msg(tr("link_lost"), th.AMBER, "⇄")
            self.pill.set_state(tr("st_offline"), th.AMBER, True)

    # ================================================================== basics
    def mark_basic_dirty(self, code: str):
        self.basic_dirty.add(code)
        self.basic_write[code].setVisible(True)
        set_prop(self.basic_write[code], "kind", "primary")

    def write_basic(self, code: str):
        p = self.ctx.cat.get(code)
        ed = self.basic_editors[code]
        try:
            raw = ed.raw()
        except (ValueError, TypeError):
            self.toast(tr("write_failed", code, "?"), error=True)
            return
        if p.stop_only and self.ctx.running:
            info(self, p.code, tr("running_warn"), warn=True)
            return
        if not self.bus.start_job("write:basic", job_write, [WriteItem(p, raw)], p.stop_only):
            self.toast(tr("busy"), error=True)

    # ================================================================== jobs
    def on_job_progress(self, tag: str, done: int, total: int, text: str):
        if tag in ("read:all", "scan", "factory:read", "factory") and getattr(self, "progress_dlg", None):
            self.progress_dlg.set_progress(done, total, text)

    def on_job_done(self, tag: str, result):
        if tag == "factory:read":
            self.close_progress()
            mode, _keep, pwd = self._factory
            from ..store import SnapshotFile, now_str, save_snapshot
            ident = self.ctx.identity or D.Identity()
            vals = {k: v for k, v in result.items() if v is not None}
            save_snapshot(SnapshotFile(name=tr("factory_saved_as", now_str()), values=vals,
                                       brand=self.ctx.settings.get("last_brand", ""),
                                       drive={"model": ident.model, "sw": ident.sw, "power": ident.power,
                                              "voltage": ident.voltage}, link=self.ctx.link_text))
            self.toast(tr("snap_saved", tr("factory_saved_as", now_str()), len(vals)))
            self.run_factory(mode, pwd)
            return
        if tag == "factory":
            self.close_progress()
            if result == D.INIT_CLEAR_FAULTS:
                self.bus.totals_at = 0
                self.toast(tr("faults_cleared"))
                return
            self.ctx.settings["pc_restore"] = {}
            self.ctx.settings.save()
            self.banner.show_msg(tr("factory_done"), th.ACCENT, "↺")
            self.bus.disconnect_drive(False)

            def again():
                self.factory_link()
                self.connect_now()
            QTimer.singleShot(1200, again)
            return
        if tag == "write:basic":
            for r in result:
                p = self.ctx.cat.get(r.code)
                if r.status in ("ok", "same"):
                    self.basic_dirty.discard(r.code)
                    self.basic_write[r.code].setVisible(False)
                    self.toast(tr("written", r.code, p.fmt(r.raw, True)))
                else:
                    self.toast(tr("write_failed", r.code, r.detail or r.status), error=True)
            self.apply_values({r.code: self.ctx.values.get(r.code) for r in result})
        elif tag == "read:all":
            self.close_progress()
            self.ctx.values.update({k: v for k, v in result.items() if v is not None})
            self.save_read(result)
        elif tag == "scan":
            self.close_progress()
            key = self.ctx.identity.bios_key if self.ctx.identity else "?"
            ranges = {g.g: min(99, g.max_index + 8) for g in self.ctx.cat.groups}
            self.ctx.fw.record_scan(key, result, ranges)
            for code in result:
                self.ctx.cat.ensure(code)
            nd = len(self.ctx.fw.diff(key, {p.code for p in self.ctx.cat.params if p.known}))
            b_ = btn(tr("cat_bios"), "small")
            b_.clicked.connect(lambda: self.open_setup(category="bios"))
            self.banner.show_msg(tr("scan_done", key, len(result), nd), th.VIOLET, "◆", [b_] if nd else [])

    def on_job_failed(self, tag: str, err: str):
        if tag in ("factory:read", "factory"):
            self.close_progress()
            info(self, tr("factory_title"), err, warn=True)
            return
        if tag in ("read:all", "scan"):
            self.close_progress()
        if tag.startswith("write:basic") or tag in ("read:all", "scan"):
            self.toast("%s: %s" % (tr("error"), err), error=True)

    def show_progress(self, title: str):
        from .dialogs import ProgressDialog
        self.progress_dlg = ProgressDialog(self, title, self.bus)
        self.progress_dlg.show()

    def close_progress(self):
        d = getattr(self, "progress_dlg", None)
        if d is not None:
            d.finish()
            self.progress_dlg = None

    def all_codes(self) -> list[str]:
        return [p.code for p in self.ctx.cat.params]

    def do_read_all(self):
        if not self.ctx.connected:
            info(self, tr("read"), tr("connect_first"))
            return
        if not self.bus.start_job("read:all", job_read, self.all_codes()):
            self.toast(tr("busy"), error=True)
            return
        self.show_progress(tr("read_progress"))

    def save_read(self, values: dict):
        from .dialogs import SaveSnapshotDialog
        dlg = SaveSnapshotDialog(self, self.ctx, values)
        if dlg.exec():
            self.toast(tr("snap_saved", dlg.saved_name, dlg.saved_count))

    def scan_bios(self):
        if not self.ctx.connected:
            return
        groups = [(g.g, min(99, g.max_index + 8)) for g in self.ctx.cat.groups]
        if not self.bus.start_job("scan", job_scan, groups):
            self.toast(tr("busy"), error=True)
            return
        self.show_progress(tr("scan_bios") + " %s" % self.ctx.identity.bios_key)

    # ================================================================== windows
    def edit_model_label(self):
        from .drive_panel import ModelLabelDialog
        if self.ctx.connected and ModelLabelDialog(self, self.ctx).exec():
            self.apply_connection_state()

    def open_factory_reset(self):
        if not self.ctx.connected:
            info(self, tr("factory_title"), tr("connect_first"))
            return
        from .drive_panel import FactoryResetDialog
        d = FactoryResetDialog(self, self.ctx)
        if not d.exec() or not d.choice:
            return
        mode, keep, pwd = d.choice
        self._factory = d.choice
        if keep and mode != D.INIT_CLEAR_FAULTS:
            if self.bus.start_job("factory:read", job_read, self.all_codes()):
                self.show_progress(tr("factory_saving"))
            else:
                self.toast(tr("busy"), error=True)
            return
        self.run_factory(mode, pwd)

    def run_factory(self, mode: int, pwd):
        from ..bus import job_factory
        if self.bus.start_job("factory", job_factory, mode, pwd):
            self.show_progress(tr("factory_running"))
        else:
            self.toast(tr("busy"), error=True)

    def open_setup(self, category: str | None = None):
        from .setup_dialog import SetupDialog
        dlg = SetupDialog(self, self.ctx, category)
        dlg.exec()
        self.apply_values(self.ctx.values)

    def open_snapshots(self):
        from .snapshots_dialog import SnapshotsDialog
        SnapshotsDialog(self, self.ctx).exec()

    def open_bios(self):
        from .dialogs import BiosDialog
        BiosDialog(self, self.ctx).exec()
        self.apply_connection_state()

    def open_prefs(self):
        from .dialogs import PrefsDialog
        if PrefsDialog(self, self.ctx).exec():
            self.bus.fast_ms = int(self.ctx.settings.get("poll_ms") or 250)

    def about(self):
        info(self, tr("about"),
             "UVFD %s\n\nWinston WSTG600 / SUSWE SU650 — Modbus RTU (RS-485)\n%s\n\n%s"
             % (VERSION, "github.com/" + __import__("uvfd.version", fromlist=["REPO"]).REPO, str(paths.HERE)))

    def switch_lang(self, code: str):
        if code == i18n.lang():
            self.bt_mk.setChecked(code == "mk")
            self.bt_en.setChecked(code == "en")
            return
        i18n.set_lang(code)
        self.ctx.settings["lang"] = code
        self.ctx.settings.save()
        old_trend, old_kpi = self.trend, self.kpi
        geo = self.saveGeometry()
        self.build()
        for s_new, s_old in zip(self.trend.series, old_trend.series):
            s_new["pts"] = s_old["pts"]
        for key, tile in self.kpi.items():
            old = old_kpi.get(key)
            if old is not None:
                tile.spark.data = old.spark.data
                tile.lo, tile.hi = old.lo, old.hi
                tile.val.setText(old.val.text())
                tile.minmax.setText(old.minmax.text())
        if self.ctx.connected:
            self.apply_connection_state()
            self.apply_values(self.ctx.values)
            self.sync_setpoint_range()
        if self.release is not None:
            self.on_update_found(self.release)
        self.restoreGeometry(geo)

    # ================================================================== recording
    def toggle_record(self):
        if self.rec_file:
            self.stop_record()
            return
        paths.LOGS.mkdir(parents=True, exist_ok=True)
        fn = paths.LOGS / ("rec_%s.csv" % datetime.now().strftime("%Y%m%d_%H%M%S"))
        self.rec_file = open(fn, "w", newline="", encoding="utf-8-sig")
        self.rec_writer = csv.writer(self.rec_file, delimiter=";")
        self.rec_writer.writerow(["time", "status", "fault"] + [m.key for m in D.MONITOR if m.idx < 12])
        self.rec_rows = 0
        self.rec_path = fn
        set_prop(self.bt_rec, "kind", "update")
        self.bt_rec.setText(tr("recording", 0))

    def record_row(self, s, val):
        if not self.rec_writer:
            return
        row = [datetime.fromtimestamp(s.t).strftime("%H:%M:%S.%f")[:-3], s.status, s.fault]
        for m in D.MONITOR:
            if m.idx < 12:
                v = val(m.key) if m.key not in ("di", "do") else s.u0.get(m.idx)
                row.append("" if v is None else str(v).replace(".", ","))
        self.rec_writer.writerow(row)
        self.rec_rows += 1
        if self.rec_rows % 4 == 0:
            self.bt_rec.setText(tr("recording", self.rec_rows))

    def stop_record(self):
        if self.rec_file:
            self.rec_file.close()
            self.rec_file = self.rec_writer = None
            set_prop(self.bt_rec, "kind", "small")
            self.bt_rec.setText("●  " + tr("record"))
            self.toast(tr("record_saved", self.rec_path.name))

    # ================================================================== updates
    def startup_checks(self):
        if updater.last_failure():
            self.banner.show_msg(tr("prev_update_failed"), th.AMBER, "⚠")
        if self.ctx.settings.get("check_updates", True):
            self.check_updates(manual=False)

    def check_updates(self, manual: bool):
        self._manual_check = manual

        def work():
            try:
                rel = updater.fetch_release()
                if rel and updater.is_newer(rel.version):
                    self.upd.found.emit(rel)
                else:
                    self.upd.none.emit(VERSION)
            except Exception as e:                       # offline is normal
                log.info("update check: %s", e)
                self.upd.failed.emit(str(e))
        threading.Thread(target=work, daemon=True).start()

    def on_update_found(self, rel):
        self.release = rel
        self.bt_update.setText("⬆  " + tr("update_available", rel.version))
        self.bt_update.show()
        if self._manual_check:
            self.show_update()

    def show_update(self):
        from .dialogs import UpdateDialog
        if self.release is not None:
            UpdateDialog(self, self.release).exec()

    # ================================================================== misc
    def toast(self, text: str, error: bool = False):
        """Status messages go to the message strip while it has no alert."""
        if not text:
            text = (tr("connected") + " — " + self.ctx.link_display()) if self.ctx.connected \
                else tr("not_connected") + " — " + tr("esc_stop")
        if self.banner.kind == "":
            self.banner.idle(text, error)
        self.sb_msg.setStyleSheet("color:%s;" % (th.RED if error else th.MUTED))
        self.sb_msg.setText(text if self.banner.kind else "")

    def update_stats(self):
        if self.bus.is_connected:
            s = self.bus.link.stats
            bad = s["err"] + s["timeouts"]
            if bad != getattr(self, "_bad_seen", 0):
                self._bad_seen, self._bad_at = bad, time.monotonic()
            recent = bad and time.monotonic() - getattr(self, "_bad_at", 0) < 60

            def seg(name, n):
                col = th.AMBER if (n and recent) else th.FAINT
                return "<span style='color:%s'>%s %d</span>" % (col, name, n)
            self.sb_stats.setTextFormat(Qt.RichText)
            self.sb_stats.setText("<span style='color:%s'>%s</span>&nbsp;&nbsp;·&nbsp;&nbsp;"
                                  "<span style='color:%s'>TX %d · OK %d</span> · %s · %s"
                                  % (th.FAINT, self.ctx.link_display(), th.FAINT, s["tx"], s["ok"],
                                     seg("ERR", s["err"]), seg("TIMEOUT", s["timeouts"])))
        else:
            self.sb_stats.setText("")

    def restore_geometry(self):
        g = self.ctx.settings.get("geometry")
        if g:
            from PySide6.QtCore import QByteArray
            try:
                self.restoreGeometry(QByteArray.fromBase64(g.encode()))
                return
            except Exception:
                pass
        self.resize(1480, 900)

    def closeEvent(self, e):
        if self.ctx.connected and not getattr(self, "_close_ok", False):
            e.ignore()

            def go():
                self._close_ok = True
                QTimer.singleShot(0, self.close)
            self.leave(then=go, closing=True)
            return
        self.stop_record()
        self.ctx.settings["geometry"] = bytes(self.saveGeometry().toBase64()).decode()
        self.ctx.settings.save()
        if self.bus.is_connected:
            self.bus.disconnect_drive(True)
            t0 = time.monotonic()
            while self.bus.is_connected and time.monotonic() - t0 < 1.5:
                time.sleep(0.05)
        self.bus.shutdown()
        e.accept()
