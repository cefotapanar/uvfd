# -*- coding: utf-8 -*-
"""
Development aid: `python main.py --shot DIR` runs the simulated drive, puts
it through its paces and saves a PNG of every window into DIR - used for the
visual review, and handy for documentation.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer

from . import drive as D
from .bus import job_scan
from .modbus import Link
from .sim import SimDrive, SimSerial
from .store import SnapshotFile, list_snapshots, save_snapshot


def _run(gen):
    try:
        while True:
            next(gen)
    except StopIteration as e:
        return e.value


class Shooter:
    def __init__(self, win, out: str):
        self.win = win
        self.ctx = win.ctx
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.steps = []
        self.t = QTimer()
        self.t.setSingleShot(True)

    def start(self):
        self.seed_bios()
        s = self.steps
        s += [(1500, self.wait_connected), (300, self.pc_on), (800, self.run), (9000, self.shot_main),
              (200, self.open_setup), (2500, self.shot_setup), (200, self.setup_bios), (900, self.shot_setup_bios),
              (200, self.close_dialog), (200, self.open_snaps), (300, self.compare), (2500, self.shot_snaps),
              (200, self.close_dialog), (200, self.open_bios), (900, self.shot_bios), (200, self.close_dialog),
              (200, self.fault), (1500, self.shot_fault), (200, self.lang_en), (2500, self.shot_main_en),
              (300, self.quit)]
        self.next()

    def next(self):
        if not self.steps:
            return
        delay, fn = self.steps.pop(0)
        QTimer.singleShot(delay, lambda: (fn(), self.next()))

    # ------------------------------------------------------------ data
    def seed_bios(self):
        fw, cat = self.ctx.fw, self.ctx.cat
        if fw.scanned("21") and fw.scanned("502"):
            return
        from .bus import Bus
        ranges = [(g.g, min(99, g.max_index + 8)) for g in cat.groups]
        for variant in ("21", "502"):
            class _B:                                    # the generator needs link + _read_block only
                pass
            b = _B()
            b.link = Link()
            b.link.open("DEMO", 9600, "N", 2, 1, serial_obj=SimSerial(SimDrive(cat, variant), latency=0))
            b._read_block = Bus._read_block.__get__(b)
            found = _run(job_scan(b, ranges))
            fw.seen(variant, "x")
            fw.versions[variant]["models"] = ["2.09"] if variant == "21" else ["1.01"]
            fw.record_scan(variant, found, dict(ranges))
            for c in found:
                cat.ensure(c)
        fw.set_base("21")
        if not list_snapshots():
            sim = SimDrive(cat, "21")
            vals = {p.code: sim.ram.get((p.g, p.i)) for p in cat.params if (p.g, p.i) in sim.ram}
            vals["P0-17"] = 50
            vals["P0-10"] = 6000
            vals["P0-12"] = 6000
            save_snapshot(SnapshotFile(name="Пумпа 2 — Котелна", values=vals, brand="Winston WSTG600",
                                       note="Клиент: Млекара Битола", drive={"model": 209, "sw": 21, "power": 22,
                                                                             "voltage": 380}))
            save_snapshot(SnapshotFile(name="Вентилатор сушара", values=dict(vals, **{"P0-17": 300}),
                                       brand="SUSWE SU650", drive={"model": 101, "sw": 502, "power": 300}))

    # ------------------------------------------------------------ steps
    def wait_connected(self):
        if not self.ctx.connected:
            self.steps.insert(0, (500, self.wait_connected))

    def pc_on(self):
        sim = self.win.bus.sim
        sim.eeprom[(0, 17)] = sim.ram[(0, 17)] = 40           # 4.0 s ramp for the demo
        sim.eeprom[(0, 18)] = sim.ram[(0, 18)] = 40
        self.win.bus.pc_control(True)

    def run(self):
        self.win.sp_hz.setValue(37.5)
        self.win.do_run(D.CMD_FWD)

    def grab(self, w, name):
        w.grab().save(str(self.out / name))

    def shot_main(self):
        self.grab(self.win, "01_main.png")

    def open_setup(self):
        from .ui.setup_dialog import SetupDialog
        self.dlg = SetupDialog(self.win, self.ctx, "g0")
        self.dlg.show()
        QTimer.singleShot(1200, lambda: self.dlg.table.selectRow(2))

    def shot_setup(self):
        self.grab(self.dlg, "02_setup.png")

    def setup_bios(self):
        self.dlg.select_category("bios")
        QTimer.singleShot(300, lambda: self.dlg.table.selectRow(0))

    def shot_setup_bios(self):
        self.grab(self.dlg, "03_setup_bios.png")

    def close_dialog(self):
        self.dlg.done(0)

    def open_snaps(self):
        from .ui.snapshots_dialog import SnapshotsDialog
        self.dlg = SnapshotsDialog(self.win, self.ctx)
        self.dlg.show()

    def compare(self):
        self.dlg.compare()

    def shot_snaps(self):
        self.grab(self.dlg, "04_load.png")

    def open_bios(self):
        from .ui.dialogs import BiosDialog
        self.dlg = BiosDialog(self.win, self.ctx)
        self.dlg.show()
        rows = self.dlg.table.rowCount()
        QTimer.singleShot(200, lambda: self.dlg.table.selectRow(rows - 1))

    def shot_bios(self):
        self.grab(self.dlg, "05_bios.png")

    def fault(self):
        self.win.bus.sim.inject_fault(11)

    def shot_fault(self):
        self.grab(self.win, "06_fault.png")

    def lang_en(self):
        self.win.bus.command(D.CMD_RESET)
        self.win.switch_lang("en")
        QTimer.singleShot(400, lambda: self.win.do_run(D.CMD_FWD))

    def shot_main_en(self):
        self.grab(self.win, "07_main_en.png")
        self.win.switch_lang("mk")

    def quit(self):
        self.win.bus.command(D.CMD_STOP)
        QTimer.singleShot(300, lambda: self.win.bus.disconnect_drive(True))
        QTimer.singleShot(900, self.win.close)
