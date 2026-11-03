# -*- coding: utf-8 -*-
"""
Core self-test - no drive, no window. Runs with pytest or on its own:

    python -m pytest tests -q
    python tests/test_core.py
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from uvfd import drive as D                               # noqa: E402
from uvfd import paths, store                             # noqa: E402
from uvfd.catalog import Catalog, parse_code              # noqa: E402
from uvfd.modbus import Link, MbBlocked, MbError, crc16   # noqa: E402
from uvfd.sim import SimDrive, SimSerial                  # noqa: E402

CAT = Catalog.load()


def sim_link(variant="21"):
    sim = SimDrive(CAT, variant)
    link = Link()
    link.open("DEMO", 9600, "N", 2, 1, serial_obj=SimSerial(sim, latency=0))
    return sim, link


# ---------------------------------------------------------------- protocol
def test_crc_known_vector():
    # 01 03 00 00 00 01 -> CRC 84 0A (Modbus reference frame)
    assert crc16(bytes([1, 3, 0, 0, 0, 1])) == (0x84, 0x0A)


def test_catalog_integrity():
    codes = [p.code for p in CAT.params]
    assert len(codes) == len(set(codes)) > 300
    for p in CAT.params:
        nums = [o[0] for o in p.options]
        assert nums == sorted(nums), p.code
        if p.ro:
            assert p.default is None, p.code
    assert [o[0] for o in CAT.get("P0-02").options] == [0, 1, 2]
    assert CAT.get("P7-11").ro and CAT.get("P0-10").dec == 2


def test_parse_code():
    assert parse_code("P0-10") == (0, 10)
    assert parse_code("pd04") == (13, 4)
    assert parse_code("PA.29") == (10, 29)
    assert parse_code("X0-10") is None


def test_signed_format_roundtrip():
    p = CAT.get("P4-23")
    assert p.signed
    assert p.fmt(64536) == "-10.00"
    assert p.parse("-10.00") == 64536
    assert CAT.get("P0-10").parse("50") == 5000


def test_read_write_through_sim():
    sim, link = sim_link()
    assert link.read_regs(0xF00A, 1) == [5000]                  # P0-10
    assert len(link.read_regs(0xF000, 12)) == 12
    try:
        link.read_regs(0xF428, 1)                               # P4-40 absent? (exists in 21)
    except MbError:
        pass
    try:
        link.read_regs(0xF0FF, 1)
        raise AssertionError("expected exception 2")
    except MbError as e:
        assert e.code == 2
    link.write_reg(0xF011, 123)                                 # P0-17
    assert link.read_strict(0xF011) == 123
    try:
        link.write_reg(0x2000, 1)
        raise AssertionError("control register must be blocked")
    except MbBlocked:
        pass


def test_run_needs_comm_command_source():
    sim, link = sim_link()
    try:
        link.write_control(D.REG_CMD, D.CMD_FWD)
        raise AssertionError("must refuse while P0-02 is not 2")
    except MbError as e:
        assert e.code == 4


def test_run_ramp_and_stop():
    sim, link = sim_link()
    link.write_reg(CAT.get("P0-02").address, 2)
    link.write_reg(CAT.get("P0-03").address, 9)
    link.write_reg(CAT.get("P0-17").address, 10)                # 1.0 s
    link.write_reg(CAT.get("P0-18").address, 10)
    link.write_control(D.REG_SETPOINT, 5000)                    # 50 % of P0-10 = 25 Hz
    link.write_control(D.REG_CMD, D.CMD_FWD)
    time.sleep(0.4)
    link.read_regs(D.REG_STATUS, 1)
    time.sleep(0.4)
    hz = link.read_regs(D.REG_U0, 1)[0] / 100
    assert 5 < hz <= 25.01, hz
    assert link.read_regs(D.REG_STATUS, 1)[0] == D.ST_FWD
    link.write_control(D.REG_CMD, D.CMD_STOP)
    for _ in range(40):
        time.sleep(0.05)
        if link.read_regs(D.REG_STATUS, 1)[0] == D.ST_STOP:
            break
    assert link.read_regs(D.REG_STATUS, 1)[0] == D.ST_STOP


def test_comm_timeout_stops_drive():
    sim, link = sim_link()
    link.write_reg(CAT.get("PD-04").ram_address, 2)             # 0.2 s, RAM only
    time.sleep(0.35)
    assert link.read_regs(D.REG_FAULT, 1)[0] == 16
    sim.power_cycle()
    assert link.read_regs(0xFD04, 1)[0] == 0                    # RAM write did not persist


def test_stop_only_param_refused_while_running():
    sim, link = sim_link()
    link.write_reg(CAT.get("P0-02").address, 2)
    link.write_control(D.REG_SETPOINT, 3000)
    link.write_control(D.REG_CMD, D.CMD_FWD)
    time.sleep(0.1)
    link.read_regs(D.REG_STATUS, 1)
    try:
        link.write_reg(CAT.get("P0-10").address, 6000)          # stop-only
        raise AssertionError("expected exception 5")
    except MbError as e:
        assert e.code == 5


# ---------------------------------------------------------------- bus jobs
def _bus_with(variant):
    from uvfd.bus import Bus
    bus = Bus(CAT)
    bus.shutdown()                                              # drive the generators by hand
    bus.link.abort.clear()
    bus.sim = SimDrive(CAT, variant)
    bus.link.open("DEMO", 9600, "N", 2, 1, serial_obj=SimSerial(bus.sim, latency=0))
    return bus


def _run(gen):
    try:
        while True:
            next(gen)
    except StopIteration as e:
        return e.value


def test_job_read_all_and_write():
    from uvfd.bus import WriteItem, job_read, job_write
    bus = _bus_with("21")
    vals = _run(job_read(bus, [p.code for p in CAT.params]))
    assert vals["P7-11"] == 21 and vals["P1-01"] == 22
    assert vals.get("PA-29") is None                            # absent in BIOS 21
    items = [WriteItem(CAT.get("P0-17"), 150), WriteItem(CAT.get("P0-10"), 6000),
             WriteItem(CAT.get("P0-12"), 6000), WriteItem(CAT.get("P7-11"), 1)]
    res = {r.code: r.status for r in _run(job_write(bus, items))}
    assert res == {"P0-10": "ok", "P0-12": "ok", "P0-17": "ok", "P7-11": "blocked"}
    res2 = {r.code: r.status for r in _run(job_write(bus, items[:1]))}
    assert res2 == {"P0-17": "same"}


def test_bios_scan_and_diff():
    from uvfd.bus import job_scan
    tmp = Path(tempfile.mkdtemp())
    reg = store.FirmwareRegistry(tmp / "fw.json")
    codes = {p.code for p in CAT.params}
    ranges = [(g.g, g.max_index + 4) for g in CAT.groups]
    for variant in ("21", "502"):
        bus = _bus_with(variant)
        found = _run(job_scan(bus, ranges))
        assert reg.seen(variant, "x") is True
        reg.record_scan(variant, found, dict(ranges))
    assert reg.base == "21"
    d = reg.diff("502", codes)
    assert d["P7-15"][0] == "added" and d["PA-29"][0] == "added"
    assert d["P4-40"][0] == "missing"
    assert reg.diff("21", codes) == {}
    assert list(reg.all_diffs(codes)) == ["502"]
    reg2 = store.FirmwareRegistry(tmp / "fw.json")              # survives a reload
    assert reg2.base == "21" and reg2.scanned("502")


def test_snapshot_roundtrip_and_vfdtool_import():
    tmp = Path(tempfile.mkdtemp())
    old = paths.SNAPSHOTS
    store.paths.SNAPSHOTS = tmp
    try:
        s = store.SnapshotFile(name="Пумпа 3 / тест", values={"P0-10": 5000, "P0-17": 100},
                               drive={"sw": 21})
        p = store.save_snapshot(s)
        assert p.exists()
        lst = store.list_snapshots()
        assert lst[0].name == "Пумпа 3 / тест" and lst[0].values["P0-17"] == 100
        store.save_snapshot(store.SnapshotFile(name="Пумпа 3 / тест"))
        assert len(store.list_snapshots()) == 2                 # no silent overwrite
        store.delete_snapshot(lst[0])
        assert len(store.list_snapshots()) == 1
    finally:
        store.paths.SNAPSHOTS = old
    old_profiles = Path(r"C:\Users\cefot\Desktop\Stvari\AI\VFDTool\vfdtool_profiles.txt")
    if old_profiles.exists():
        profs = store.import_vfdtool(old_profiles)
        assert profs and all(len(p.values) > 100 for p in profs)


def test_find_drive_on_other_address():
    from uvfd.bus import ConnectSpec
    bus = _bus_with("21")
    bus.link.close()
    bus.sim = SimDrive(CAT, "21", slave=3)                     # drive at address 3, we start at 1
    got = []
    bus.connected.connect(lambda info: got.append(info))
    bus._do_connect(ConnectSpec(port="DEMO", baud=9600, fmt=0, slave=1, demo="21", scan=True,
                                comm_timeout=0))
    assert got and got[0]["slave"] == 3 and got[0]["identity"].sw == 21


def test_connect_diagnosis():
    from uvfd.bus import ConnectSpec
    bus = _bus_with("21")
    bus.link.close()
    bus.sim = SimDrive(CAT, "21", slave=5)                     # wrong address -> nothing comes back
    fails = []
    bus.connect_failed.connect(fails.append)
    bus._do_connect(ConnectSpec(port="DEMO", baud=9600, fmt=0, slave=1, demo="21", comm_timeout=0))
    assert fails and "НИКАКОВ" in fails[0] and "#1" in fails[0]
    spec = ConnectSpec(port="COM9", baud=9600, fmt=0, slave=1)
    bus.link.stats.update(rx=48, echo=48)                      # only our own frames came back
    assert "ехо" in bus._diagnosis(spec)
    bus.link.stats.update(rx=50, echo=0)                       # bytes, but unreadable
    assert "брзината (PD-00)" in bus._diagnosis(spec)


def test_settings_move_to_factory_link_once():
    import json
    tmp = Path(tempfile.mkdtemp())
    old = paths.DATA
    store.paths.DATA = tmp
    try:
        (tmp / "settings.json").write_text(json.dumps({"lang": "en", "baud": None, "fmt": 3, "slave": 7}),
                                           encoding="utf-8")
        st = store.Settings()
        assert (st["baud"], st["fmt"], st["slave"], st["lang"]) == (9600, 0, 1, "en")
        st["slave"] = 4
        st.save()
        assert store.Settings()["slave"] == 4                    # only once - a later choice stays
    finally:
        store.paths.DATA = old


def test_progress_dialog_closes():
    """1.1.0: the progress window stuck at 100% and ignored X - it must close on all three paths."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from uvfd.ui.dialogs import ProgressDialog

    class FakeBus:
        cancelled = 0

        def cancel_job(self):
            FakeBus.cancelled += 1

    for how in ("finish", "x", "cancel_button"):
        d = ProgressDialog(None, "t", FakeBus())
        d.show()
        app.processEvents()
        d.set_progress(10, 10, "P9")
        if how == "finish":
            d.finish()
        elif how == "x":
            d.close()                                   # the window's X goes through close()
        else:
            d.reject()
        app.processEvents()
        assert not d.isVisible(), how
    assert FakeBus.cancelled == 2                       # finish() does not cancel a finished job


def _main_window(tmp):
    """A real MainWindow (offscreen) on a temp data folder, with its own bus."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    store.paths.DATA = tmp
    store.paths.SNAPSHOTS = tmp / "snapshots"
    from uvfd.bus import Bus
    from uvfd.ui import theme as th
    from uvfd.ui.common import Ctx
    from uvfd.ui.main_window import MainWindow
    th.init_fonts()
    bus = Bus(CAT)
    ctx = Ctx(cat=CAT, bus=bus, settings=store.Settings(), fw=store.FirmwareRegistry(tmp / "fw.json"))
    ctx.settings["check_updates"] = False
    win = MainWindow(ctx)
    return app, win, bus


def _wait(app, cond, seconds):
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def test_search_cancel_closes_and_frees_the_app():
    """The user hit this twice: Cancel / X during "Find drive" left a window nothing could close."""
    old_data, old_snaps = paths.DATA, paths.SNAPSHOTS
    try:
        for how in ("cancel_button", "x"):
            app, win, bus = _main_window(Path(tempfile.mkdtemp()))
            bus.sim = SimDrive(CAT, "21", slave=200)              # never found at 1..10
            win.cb_port.addItem("DEMO 21", "DEMO:21")
            win.cb_port.setCurrentIndex(win.cb_port.count() - 1)
            win.search_drive()
            dlg = win.scan_dlg
            assert _wait(app, lambda: dlg.bar.value() > 3, 10), "search did not start"
            if how == "x":
                dlg.close()
            else:
                dlg.reject()
            assert _wait(app, lambda: not dlg.isVisible(), 3), how + ": window still open"
            assert _wait(app, lambda: win.bt_connect.isEnabled(), 5), how + ": app stuck in connecting"
            assert not bus.is_connected
            assert win.banner.kind == "", "a cancel is not an error"
            win.bus.shutdown()
            win.deleteLater()
            app.processEvents()
    finally:
        store.paths.DATA, store.paths.SNAPSHOTS = old_data, old_snaps


def _pc_scenario(prepare_sim, script):
    """Connect the demo drive in a real MainWindow with scripted answers to the questions."""
    import uvfd.ui.main_window as mw
    old = (mw.ask, mw.choose, paths.DATA, paths.SNAPSHOTS)
    asked = []
    mw.ask = lambda *a, **k: True
    mw.choose = lambda parent, title, text, options, default=0: (asked.append(text), script(text))[1]
    try:
        app, win, bus = _main_window(Path(tempfile.mkdtemp()))
        bus.sim = SimDrive(CAT, "21")
        sim = bus.sim
        sim.ram[(0, 18)] = sim.eeprom[(0, 18)] = 10              # 1.0 s deceleration
        prepare_sim(sim)
        win.connect_now(demo_variant="21")
        assert _wait(app, lambda: win.ctx.connected, 10), "no connection"
        return app, win, bus, sim, asked
    finally:
        mw.ask, mw.choose = old[0], old[1]
        mw._old = old


def _pc_done():
    import uvfd.ui.main_window as mw
    store.paths.DATA, store.paths.SNAPSHOTS = mw._old[2], mw._old[3]


def test_disconnect_restores_mode_uvfd_set():
    import uvfd.ui.main_window as mw
    app, win, bus, sim, asked = _pc_scenario(lambda sim: None, lambda text: 0)
    try:
        assert (sim.ram[(0, 2)], sim.ram[(0, 3)]) == (0, 4)       # BIOS 21 demo: keypad + potentiometer
        mw.ask, mw.choose = (lambda *a, **k: True), (lambda p, t, text, o, d=0: (asked.append(text), 0)[1])
        win.on_pc_toggle(True)
        assert _wait(app, lambda: sim.ram[(0, 2)] == 2 and win.pc_active(), 5)
        assert win.pc_ours()
        win.sp_hz.setValue(20)
        win.do_run(D.CMD_FWD)
        assert _wait(app, lambda: win.ctx.running, 5)
        win.disconnect_now()                                      # restore -> stops the motor first
        assert _wait(app, lambda: not bus.is_connected, 15), "did not disconnect"
        assert len(asked) == 1 and "P0-02" in asked[0]
        assert (sim.ram[(0, 2)], sim.ram[(0, 3)]) == (0, 4), "old mode not restored"
        assert sim.ram[(13, 4)] == 0                              # PD-04 back
        assert win.ctx.settings.get("pc_restore") == {}
        bus.shutdown()
    finally:
        _pc_done()


def test_disconnect_does_not_ask_when_pc_was_already_on():
    def already_pc(sim):
        for k, v in (((0, 2), 2), ((0, 3), 9)):
            sim.ram[k] = sim.eeprom[k] = v

    def must_not_ask(text):
        raise AssertionError("asked although UVFD did not turn PC control on: " + text)
    app, win, bus, sim, asked = _pc_scenario(already_pc, must_not_ask)
    try:
        import uvfd.ui.main_window as mw
        mw.choose = lambda *a, **k: must_not_ask(a[2])
        assert win.pc_active() and not win.pc_ours()
        win.disconnect_now()
        assert _wait(app, lambda: not bus.is_connected, 5)
        assert sim.ram[(0, 2)] == 2                               # left exactly as it was
        bus.shutdown()
    finally:
        _pc_done()


def test_close_can_keep_pc_mode():
    app, win, bus, sim, asked = _pc_scenario(lambda sim: None, lambda text: 1)
    try:
        import uvfd.ui.main_window as mw
        mw.ask, mw.choose = (lambda *a, **k: True), (lambda p, t, text, o, d=0: (asked.append(text), 1)[1])
        win.on_pc_toggle(True)
        assert _wait(app, lambda: sim.ram[(0, 2)] == 2 and win.pc_active(), 5)
        win.close()                                               # "Disconnect, keep PC"
        assert _wait(app, lambda: not bus.is_connected, 5)
        assert len(asked) == 1 and sim.ram[(0, 2)] == 2 and sim.ram[(13, 4)] == 0
    finally:
        _pc_done()


def test_version_compare():
    from uvfd.updater import is_newer
    assert is_newer("1.10.0", "1.9.0")
    assert not is_newer("1.0.0", "1.0.0")
    assert is_newer("v1.0.1", "1.0.0")


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok   ", name)
            except Exception as e:                              # noqa: BLE001
                fails += 1
                print("FAIL ", name, "-", repr(e))
    print("\n%s" % ("ALL PASSED" if not fails else "%d FAILED" % fails))
    sys.exit(1 if fails else 0)
