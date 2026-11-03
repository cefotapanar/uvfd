# -*- coding: utf-8 -*-
"""
The bus worker - the ONLY code that talks on the RS-485 cable.

One thread, one master on the bus, so two requests are never in flight at
once. Its loop, in priority order:

  1. commands (start / stop / setpoint / reset) - always next on the wire,
     so STOP never waits behind a 30-second "Read all";
  2. the monitoring poll (fast block every 250 ms, the rest less often);
  3. one step of the current long job (read all, BIOS scan, write a set).

Long jobs are generators that do one or two requests per step, so the loop
gets back to commands and polling between steps. Polling never stops while
connected - with the PD-04 communication timeout set, silence stops the drive
(Err16), which is exactly the point.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

from . import drive as D
from .catalog import Catalog, Param, make_code, parse_code, write_rank
from .modbus import CHUNK, FORMATS, Link, MbBlocked, MbError, MbTimeout, exc_text

log = logging.getLogger("uvfd.bus")


@dataclass
class ConnectSpec:
    port: str
    baud: int | None = 9600          # None = auto
    fmt: int | None = 0              # PD-01 value, None = auto
    slave: int = 1
    demo: str | None = None          # BIOS variant for the simulator
    comm_timeout: float = 2.0        # PD-04 while the PC drives the motor; 0 = leave it
    scan: bool = False               # search every baud / format / address 1..max_addr
    max_addr: int = 10


@dataclass
class WriteItem:
    param: Param
    raw: int


@dataclass
class WriteResult:
    code: str
    raw: int
    status: str                      # ok / same / refused / noanswer / verify / blocked / skipped
    detail: str = ""


@dataclass
class Job:
    tag: str
    gen: object
    started: float = field(default_factory=time.monotonic)


class Bus(QObject):
    connected = Signal(object)            # dict: identity, values, link text
    connect_failed = Signal(str)
    connect_progress = Signal(str, int, int)   # what is being tried, n, total
    connect_cancelled = Signal()
    disconnected = Signal(str)
    snapshot = Signal(object)             # drive.Snapshot
    values = Signal(object, str)          # {code: raw}, why ("basics", "totals", "group", ...)
    job_progress = Signal(str, int, int, str)
    job_done = Signal(str, object)
    job_failed = Signal(str, str)
    command_done = Signal(str, bool, str)
    link_state = Signal(bool)             # False = polls failing (cable?), True = back

    def __init__(self, catalog: Catalog, lang_fn=lambda: "mk"):
        super().__init__()
        self.cat = catalog
        self.lang = lang_fn
        self.link = Link()
        self.sim = None
        self.spec: ConnectSpec | None = None
        self.urgent: queue.Queue = queue.Queue()
        self.requests: queue.Queue = queue.Queue()
        self.job: Job | None = None
        self.cancel_flag = threading.Event()
        self.scan_cancel = threading.Event()
        self.wake = threading.Event()
        self.stop_flag = threading.Event()
        self.fast_ms = 250
        self.slow_ms = 1500
        self.values_cache: dict[str, int] = {}
        self.max_hz = 50.0
        self.setpoint_hz = 0.0
        self.last_status = -1
        self.pd04_orig: int | None = None
        self.pd04_set = False
        self.bad_u0: set[int] = set()
        self.fail_streak = 0
        self.link_ok = True
        self.totals_at = 0.0
        self.thread = threading.Thread(target=self._run, name="uvfd-bus", daemon=True)
        self.thread.start()

    # ======================================================== public API (any thread)
    @property
    def is_connected(self) -> bool:
        return self.link.is_open

    def connect_drive(self, spec: ConnectSpec):
        self.requests.put(("connect", spec))
        self.wake.set()

    def cancel_connect(self):
        self.scan_cancel.set()

    def disconnect_drive(self, restore_timeout: bool = True):
        self.link.abort.set()
        self.requests.put(("disconnect", restore_timeout))
        self.wake.set()

    def command(self, cmd: int):
        self.urgent.put(("cmd", cmd))
        self.wake.set()

    def set_frequency(self, hz: float):
        self.urgent.put(("hz", float(hz)))
        self.wake.set()

    def pc_control(self, on: bool, restore: dict | None = None):
        """P0-02/P0-03 to communication (persistent) + PD-04 timeout (RAM)."""
        self.urgent.put(("pc", on, restore or {}))
        self.wake.set()

    def start_job(self, tag: str, factory, *args) -> bool:
        if self.job is not None:
            return False
        self.requests.put(("job", tag, factory, args))
        self.wake.set()
        return True

    def cancel_job(self):
        self.cancel_flag.set()

    def busy(self) -> bool:
        return self.job is not None

    def shutdown(self):
        self.stop_flag.set()
        self.link.abort.set()
        self.wake.set()
        self.thread.join(timeout=3)

    # ======================================================== the loop
    def _run(self):
        next_fast = next_slow = next_basics = 0.0
        while not self.stop_flag.is_set():
            try:
                self._take_requests()
                if not self.link.is_open:
                    self.wake.wait(0.2)
                    self.wake.clear()
                    continue
                self._do_urgent()
                now = time.monotonic()
                if now >= next_fast:
                    self._poll_fast()
                    period = self.fast_ms if self.job is None else max(self.fast_ms, 600)
                    next_fast = now + period / 1000.0
                    continue
                if self.job is None and now >= next_slow:
                    self._poll_slow()
                    next_slow = now + self.slow_ms / 1000.0
                    continue
                if self.job is None and now >= next_basics:
                    self._emit_values(self.read_codes(D.BASICS), "basics")
                    next_basics = now + 5.0
                    continue
                if self.job is None and now >= self.totals_at:
                    self._emit_values(self.read_codes(D.TOTALS), "totals")
                    self.totals_at = now + 15.0
                    continue
                if self.job is not None:
                    self._job_step()
                    continue
                wait = max(0.0, min(next_fast, next_slow) - time.monotonic())
                self.wake.wait(min(wait, 0.05))
                self.wake.clear()
            except Exception as e:                      # never let the bus thread die
                log.exception("bus loop")
                self.job_failed.emit(self.job.tag if self.job else "", str(e))
                self.job = None
                time.sleep(0.2)

    def _take_requests(self):
        while True:
            try:
                req = self.requests.get_nowait()
            except queue.Empty:
                return
            kind = req[0]
            if kind == "connect":
                self._do_connect(req[1])
            elif kind == "disconnect":
                self._do_disconnect(req[1])
            elif kind == "job":
                _, tag, factory, args = req
                if not self.link.is_open:
                    self.job_failed.emit(tag, self._t("Нема врска со фреквентен.", "Not connected."))
                elif self.job is not None:
                    self.job_failed.emit(tag, self._t("Друга работа е во тек.", "Another job is running."))
                else:
                    self.cancel_flag.clear()
                    self.job = Job(tag, factory(self, *args))

    def _t(self, mk: str, en: str) -> str:
        return mk if self.lang() == "mk" else en

    # ======================================================== connect / disconnect
    def _open(self, spec: ConnectSpec, baud: int, fmt: int, timeout: float = 0.35):
        parity, stop = FORMATS[fmt]
        if spec.demo:
            from .sim import SimDrive, SimSerial
            if self.sim is None or self.sim.variant != spec.demo:
                self.sim = SimDrive(self.cat, spec.demo, slave=spec.slave)
            self.link.open("DEMO", baud, parity, stop, spec.slave, serial_obj=SimSerial(self.sim))
        else:
            self.link.open(spec.port, baud, parity, stop, spec.slave, timeout=timeout)

    def _probe(self) -> bool:
        try:
            self.link.read_regs(0xF000, 1)               # P0-00 always exists
            return True
        except MbError:
            return True                                  # it answered, so the line is right
        except MbTimeout:
            return False

    def _do_connect(self, spec: ConnectSpec):
        if self.link.is_open:
            self._do_disconnect(True)
        self.link.abort.clear()
        self.spec = spec
        self.bad_u0.clear()
        self.values_cache.clear()
        self.pd04_orig, self.pd04_set = None, False
        for k in self.link.stats:
            self.link.stats[k] = 0
        self.scan_cancel.clear()
        try:
            found = self._search(spec) if spec.scan else self._try(spec)
            if found is None:                       # cancelled - not an error
                self.link.close()
                self.connect_cancelled.emit()
                return
            if not found:
                self.link.close()
                self.connect_failed.emit(self._diagnosis(spec))
                return
        except Exception as e:
            self.link.close()
            self.connect_failed.emit(self._t("Портата %s не може да се отвори (можеби ја држи друга програма, "
                                             "на пр. VFDTool): " % spec.port,
                                             "Cannot open %s (another program, e.g. VFDTool, may hold it): "
                                             % spec.port) + str(e))
            return

        vals = self.read_codes(D.IDENTITY + D.BASICS + D.TOTALS)
        self.values_cache.update({k: v for k, v in vals.items() if v is not None})
        self._update_max_hz()
        self.pd04_orig = vals.get("PD-04")
        if vals.get("P0-02") == D.P002_COMM:
            self._apply_timeout(True)
        info = {
            "identity": D.Identity.from_values(vals),
            "values": vals,
            "link": self.link.describe(),
            "baud": self.link.baud,
            "slave": self.link.slave,
            "fmt": next(k for k, v in FORMATS.items() if v == (self.link.parity, self.link.stopbits)),
            "demo": spec.demo,
        }
        self.fail_streak, self.link_ok = 0, True
        log.info("connected %s, BIOS %s", self.link.describe(), info["identity"].bios_key)
        self.connected.emit(info)

    FMT_NAME = {0: "8N2", 1: "8E1", 2: "8O1", 3: "8N1"}
    SEARCH_BAUDS = [9600, 19200, 38400, 4800, 2400, 1200, 57600, 115200]
    SEARCH_FMTS = [0, 1, 3, 2]

    def _try(self, spec: ConnectSpec) -> bool:
        """The chosen settings ("Auto" tries every baud / format at the chosen address)."""
        bauds = [spec.baud] if spec.baud else self.SEARCH_BAUDS
        fmts = [spec.fmt] if spec.fmt is not None else self.SEARCH_FMTS
        total, n = len(bauds) * len(fmts), 0
        for b in bauds:
            for f in fmts:
                if self.scan_cancel.is_set():
                    return None
                n += 1
                self.connect_progress.emit("%d %s #%d" % (b, self.FMT_NAME[f], spec.slave), n, total)
                self._open(spec, b, f, timeout=0.35 if total == 1 else 0.25)
                if self._probe():
                    return True
                self.link.close()
        return False

    def _search(self, spec: ConnectSpec) -> bool:
        """
        Every baud x format, address 1 first (factory), then 2..max_addr.
        The port is opened once per baud/format; only the address changes.
        """
        passes = [[spec.slave] if spec.slave != 1 else [1]]
        rest = [a for a in range(1, spec.max_addr + 1) if a not in passes[0]]
        if rest:
            passes.append(rest)
        total = sum(len(p) for p in passes) * len(self.SEARCH_BAUDS) * len(self.SEARCH_FMTS)
        n = 0
        for addrs in passes:
            for b in self.SEARCH_BAUDS:
                for f in self.SEARCH_FMTS:
                    self._open(spec, b, f, timeout=0.2)
                    for a in addrs:
                        if self.scan_cancel.is_set():
                            return None
                        n += 1
                        self.link.slave = a
                        self.connect_progress.emit("%d %s #%d" % (b, self.FMT_NAME[f], a), n, total)
                        if self._probe():
                            spec.slave = a
                            return True
                    self.link.close()
        return False

    def _diagnosis(self, spec: ConnectSpec) -> str:
        """What the failure most likely is, from what came back on the wire."""
        s = self.link.stats
        tried = "%s · %s" % (spec.port, self._t("сите брзини, формати и адреси 1–%d" % spec.max_addr,
                                                 "every baud, format and address 1–%d" % spec.max_addr)) \
            if spec.scan else "%s · %s %s · #%d" % (spec.port, spec.baud or self._t("авто", "auto"),
                                                    self.FMT_NAME.get(spec.fmt, self._t("авто", "auto")), spec.slave)
        if s["rx"] == 0:
            why = self._t("Нема НИКАКОВ сигнал назад. Најчесто: A и B се заменети (замени ги), фреквентниот "
                          "не е вклучен, или е избрана погрешна порта.",
                          "NOTHING comes back. Most often: A and B are swapped (swap them), the drive is not "
                          "powered, or the wrong port is selected.")
        elif s["echo"] and s["echo"] >= s["rx"] * 0.8:
            why = self._t("Адаптерот го враќа само тоа што праќаме (ехо) - фреквентниот не одговара. Провери "
                          "A/B, адресата (PD-02) и на SU650 PD-08 = 0 (Slave).",
                          "The adapter only echoes what we send - the drive does not answer. Check A/B, the "
                          "address (PD-02) and on SU650 PD-08 = 0 (Slave).")
        else:
            why = self._t("Стигнува сигнал, но не се разбира - брзината (PD-00) или форматот (PD-01) не се исти "
                          "како во програмата, или PD-05 не е 1. Пробај „Пребарај фреквентен“.",
                          "Something comes back but cannot be read - baud (PD-00) or format (PD-01) differ from "
                          "the program, or PD-05 is not 1. Try “Find drive”.")
        return self._t("Нема одговор (%s). " % tried, "No answer (%s). " % tried) + why

    def _do_disconnect(self, restore_timeout: bool):
        if self.job is not None:
            self.job_failed.emit(self.job.tag, self._t("Прекинато - врската е затворена.", "Aborted - link closed."))
            self.job = None
        if self.link.is_open:
            self.link.abort.clear()
            if restore_timeout and self.pd04_set:
                self._apply_timeout(False)
            self.link.close()
            self.disconnected.emit("")
        self.link.abort.clear()

    # ======================================================== PD-04 timeout
    def _apply_timeout(self, on: bool):
        """PD-04 in RAM only: a power cycle brings back the drive's own value."""
        if self.spec is None:
            return
        want = int(round(self.spec.comm_timeout * 10)) if on else (self.pd04_orig or 0)
        if on and want <= 0:
            return
        try:
            self.link.write_reg(self.cat.get("PD-04").ram_address, want)
            self.pd04_set = on
            self.values_cache["PD-04"] = want
            log.info("PD-04 (RAM) = %.1f s", want / 10)
        except (MbError, MbTimeout, MbBlocked) as e:
            log.warning("PD-04 write failed: %s", e)
            # the safety net is NOT in place - the operator has to know
            detail = exc_text(e.code, self.lang()) if isinstance(e, MbError) else str(e)
            self.command_done.emit("pd04", False, "PD-04 timeout: " + detail)

    # ======================================================== commands
    def _update_max_hz(self):
        v = self.values_cache.get("P0-10")
        if v:
            dec = 1 if self.values_cache.get("P0-22") == 1 else 2
            self.max_hz = v / (10 ** dec)

    def _do_urgent(self):
        while True:
            try:
                item = self.urgent.get_nowait()
            except queue.Empty:
                return
            kind = item[0]
            try:
                if kind == "cmd":
                    cmd = item[1]
                    if cmd in (D.CMD_FWD, D.CMD_REV):
                        self._send_setpoint(self.setpoint_hz)
                    self.link.write_control(D.REG_CMD, cmd)
                    self.command_done.emit("cmd%d" % cmd, True, "")
                elif kind == "hz":
                    self.setpoint_hz = item[1]
                    self._send_setpoint(item[1])
                    self.command_done.emit("hz", True, "")
                elif kind == "pc":
                    self._do_pc(item[1], item[2])
            except MbError as e:
                self.command_done.emit(kind, False, exc_text(e.code, self.lang()))
            except (MbTimeout, MbBlocked) as e:
                self.command_done.emit(kind, False, str(e))

    def _send_setpoint(self, hz: float):
        pct = 0 if self.max_hz <= 0 else round(hz / self.max_hz * 10000)
        pct = max(-10000, min(10000, pct))
        self.link.write_control(D.REG_SETPOINT, pct & 0xFFFF)

    def _do_pc(self, on: bool, restore: dict):
        if on:
            for code, val in (("P0-02", D.P002_COMM), ("P0-03", D.P003_COMM)):
                p = self.cat.get(code)
                if self.values_cache.get(code) != val:
                    self.link.write_reg(p.address, val)
                    self.values_cache[code] = val
            self._apply_timeout(True)
        else:
            self._apply_timeout(False)
            for code in ("P0-03", "P0-02"):
                if code in restore and restore[code] is not None:
                    self.link.write_reg(self.cat.get(code).address, restore[code])
                    self.values_cache[code] = restore[code]
        vals = self.read_codes(["P0-02", "P0-03", "PD-04"])
        self._emit_values(vals, "basics")
        self.command_done.emit("pc", True, "")

    # ======================================================== polling
    def _note(self, ok: bool):
        if ok:
            self.fail_streak = 0
            if not self.link_ok:
                self.link_ok = True
                self.link_state.emit(True)
        else:
            self.fail_streak += 1
            if self.fail_streak >= 4 and self.link_ok:
                self.link_ok = False
                self.link_state.emit(False)

    def _read_u0_block(self, start: int, n: int, out: dict):
        idxs = [i for i in range(start, start + n)]
        if not any(i not in self.bad_u0 for i in idxs):
            return
        try:
            vals = self.link.read_regs(D.REG_U0 | start, n)
            out.update(dict(zip(idxs, vals)))
        except MbError:
            for i in idxs:
                if i in self.bad_u0:
                    continue
                try:
                    out[i] = self.link.read_regs(D.REG_U0 | i, 1)[0]
                except MbError:
                    self.bad_u0.add(i)

    def _poll_fast(self):
        s = D.Snapshot(t=time.time())
        try:
            self._read_u0_block(*D.FAST_BLOCK, s.u0)
            s.status = self.link.read_regs(D.REG_STATUS, 1)[0]
            s.fault = self.link.read_regs(D.REG_FAULT, 1)[0]
            s.ok = True
        except (MbTimeout, MbError) as e:
            s.error = str(e)
        self._note(s.ok)
        if s.ok:
            self.last_status = s.status
        self.snapshot.emit(s)

    def _poll_slow(self):
        s = D.Snapshot(t=time.time())
        try:
            for start, n in D.SLOW_BLOCKS:
                self._read_u0_block(start, n, s.u0)
            for i in D.SLOW_SINGLES:
                if i not in self.bad_u0:
                    try:
                        s.u0[i] = self.link.read_regs(D.REG_U0 | i, 1)[0]
                    except MbError:
                        self.bad_u0.add(i)
            s.ok = True
        except MbTimeout as e:
            s.error = str(e)
        s.status = -2                       # marks a slow (partial) snapshot
        if s.ok:
            self.snapshot.emit(s)

    def _emit_values(self, vals: dict, why: str):
        got = {k: v for k, v in vals.items() if v is not None}
        self.values_cache.update(got)
        if "P0-10" in got or "P0-22" in got:
            self._update_max_hz()
        self.values.emit(vals, why)

    # ======================================================== parameter reads
    def read_codes(self, codes, progress=None) -> dict:
        """{code: raw or None}; consecutive indexes go in blocks of 12."""
        out: dict[str, int | None] = {}
        by_group: dict[int, list[int]] = {}
        for c in codes:
            gi = parse_code(c)
            if gi:
                by_group.setdefault(gi[0], []).append(gi[1])
        for g, idxs in sorted(by_group.items()):
            for start, n in runs_of(sorted(set(idxs))):
                pos = start
                while pos < start + n:
                    k = min(CHUNK, start + n - pos)
                    out.update(self._read_block(g, pos, k))
                    pos += k
        return out

    def _read_block(self, g: int, start: int, n: int) -> dict:
        base = 0xF000 | (g << 8)
        res = {}
        try:
            vals = self.link.read_regs(base + start, n)
            for k in range(n):
                res[make_code(g, start + k)] = vals[k]
            return res
        except MbError:
            pass
        except MbTimeout:
            if n == 1:
                return {make_code(g, start): None}
        for k in range(n):
            try:
                res[make_code(g, start + k)] = self.link.read_regs(base + start + k, 1)[0]
            except (MbError, MbTimeout):
                res[make_code(g, start + k)] = None
        return res

    def read_strict(self, p: Param) -> int | None:
        for attempt in range(2):
            try:
                return self.link.read_strict(p.address)
            except MbError:
                return None
            except MbTimeout:
                continue
        return None

    # ======================================================== jobs
    def _job_step(self):
        job = self.job
        if self.cancel_flag.is_set():
            self.cancel_flag.clear()
            try:
                job.gen.close()
            except Exception:
                pass
            self.job = None
            self.job_failed.emit(job.tag, self._t("Откажано.", "Cancelled."))
            return
        try:
            done, total, text = next(job.gen)
            self.job_progress.emit(job.tag, done, total, text)
        except StopIteration as e:
            self.job = None
            self.job_done.emit(job.tag, e.value)
        except JobError as e:
            self.job = None
            self.job_failed.emit(job.tag, str(e))
        except (MbTimeout, MbError) as e:
            self.job = None
            self.job_failed.emit(job.tag, str(e))


class JobError(Exception):
    pass


def runs_of(idxs: list[int]) -> list[tuple[int, int]]:
    """[0,1,2,7] -> [(0,3),(7,1)]"""
    out, i = [], 0
    while i < len(idxs):
        start, n = idxs[i], 1
        while i + n < len(idxs) and idxs[i + n] == start + n:
            n += 1
        out.append((start, n))
        i += n
    return out


# ============================================================ job generators
# Each one yields (done, total, text) after every request or two, and returns
# its result.

def job_read(bus: Bus, codes: list[str]):
    """Read the given parameter codes."""
    codes = sorted(set(codes), key=lambda c: parse_code(c))
    out = {}
    plan = []
    by_group: dict[int, list[int]] = {}
    for c in codes:
        g, i = parse_code(c)
        by_group.setdefault(g, []).append(i)
    for g, idxs in sorted(by_group.items()):
        for start, n in runs_of(sorted(idxs)):
            pos = start
            while pos < start + n:
                k = min(CHUNK, start + n - pos)
                plan.append((g, pos, k))
                pos += k
    total = sum(k for _, _, k in plan)
    done = 0
    for g, pos, k in plan:
        out.update(bus._read_block(g, pos, k))
        done += k
        yield done, total, "P%s" % "0123456789ABCDEF"[g]
    bus._emit_values(out, "read")
    return out


def job_scan(bus: Bus, groups: list[tuple[int, int]]):
    """
    BIOS fingerprint: which registers exist in each group (0..last index).
    `groups` is [(g, last_index)]. Returns {code: raw} of everything that
    answered.
    """
    total = sum(last + 1 for _, last in groups)
    done = 0
    found = {}
    for g, last in groups:
        pos = 0
        while pos <= last:
            k = min(CHUNK, last - pos + 1)
            res = bus._read_block(g, pos, k)
            found.update({c: v for c, v in res.items() if v is not None})
            pos += k
            done += k
            yield done, total, "P%s-%02d" % ("0123456789ABCDEF"[g], min(pos, last))
    return found


def job_write(bus: Bus, items: list[WriteItem], require_stop: bool = True):
    """Write in the safe order, read back and verify each value."""
    lang = bus.lang()
    if require_stop:
        st = bus.link.read_regs(D.REG_STATUS, 1)[0]
        if st != D.ST_STOP:
            raise JobError("Моторот работи - запри го пред запишување." if lang == "mk"
                           else "The motor is running - stop it before writing.")
    items = sorted(items, key=lambda it: write_rank(it.param))
    results = []
    for n, it in enumerate(items):
        p = it.param
        if p.ro:
            results.append(WriteResult(p.code, it.raw, "blocked", "read only"))
            continue
        cur = bus.read_strict(p)
        if cur is not None and cur == it.raw:
            results.append(WriteResult(p.code, it.raw, "same"))
        else:
            try:
                bus.link.write_reg(p.address, it.raw)
                rb = bus.read_strict(p)
                if rb == it.raw:
                    results.append(WriteResult(p.code, it.raw, "ok"))
                    bus.values_cache[p.code] = it.raw
                else:
                    results.append(WriteResult(p.code, it.raw, "verify",
                                               "read back %s" % ("-" if rb is None else rb)))
            except MbError as e:
                results.append(WriteResult(p.code, it.raw, "refused", exc_text(e.code, lang)))
            except MbBlocked as e:
                results.append(WriteResult(p.code, it.raw, "blocked", str(e)))
            except MbTimeout as e:
                results.append(WriteResult(p.code, it.raw, "noanswer", str(e)))
        yield n + 1, len(items), p.code
    vals = {r.code: r.raw for r in results if r.status in ("ok", "same")}
    bus._emit_values(vals, "write")
    return results
