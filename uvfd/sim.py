# -*- coding: utf-8 -*-
"""
Simulated WSTG600 / SU650 on a fake serial port - DEMO mode and the tests.

It speaks real Modbus RTU frames (CRC, exceptions, 12-register limit), so the
same code path is exercised as with a drive on the cable. Two BIOS variants
are built in so the BIOS-difference feature can be seen without hardware:

    21   values from a real 2.2 kW drive (VFDTool archive, M209-S21)
    502  values from a real 30 kW drive (M101-S502), plus a few extra and
         missing registers so a scan has something to find
"""

from __future__ import annotations

import math
import random
import threading
import time

from . import drive as D
from .catalog import Catalog, parse_code
from .modbus import crc16, with_crc

# Values read off real drives (VFDTool arhiva/snimki), only where they differ
# from the catalog factory value - enough to look like the real thing.
VARIANTS = {
    "21": {
        "P0-02": 0, "P0-03": 4, "P0-15": 40, "P0-17": 100, "P0-18": 100, "P0-23": 1,
        "P1-00": 0, "P1-01": 22, "P1-02": 380, "P1-03": 510, "P1-04": 5000, "P1-05": 1460,
        "P1-06": 2706, "P1-07": 1543, "P1-08": 1011, "P1-09": 2450, "P1-10": 267,
        "P7-07": 32, "P7-08": 60000, "P7-09": 609, "P7-10": 209, "P7-11": 21,
        "P7-13": 5293, "P7-14": 123, "P9-14": 9, "P9-15": 9, "P9-16": 10, "PD-06": 0,
    },
    "502": {
        "P0-02": 1, "P0-03": 2, "P0-10": 5000, "P0-12": 5000, "P0-15": 50, "P0-17": 180,
        "P0-18": 130, "P1-00": 1, "P1-01": 300, "P1-02": 400, "P1-03": 5600, "P1-04": 5000,
        "P1-05": 1470, "P1-06": 32, "P1-07": 38, "P1-08": 34, "P1-09": 322, "P1-10": 2070,
        "P7-07": 31, "P7-08": 50000, "P7-09": 1210, "P7-10": 101, "P7-11": 502,
        "P7-13": 3, "P7-14": 8, "P8-13": 1, "P9-14": 10, "P9-15": 9, "P9-16": 9, "PD-06": 0,
    },
}
# BIOS 502 knows a few registers 21 does not, and lost one.
EXTRA = {"502": {"P7-15": 1, "P7-16": 0, "P8-54": 0, "PA-29": 0}}
MISSING = {"502": {"P4-40"}, "21": {"PA-29"}}


class SimDrive:
    def __init__(self, catalog: Catalog, variant: str = "21", slave: int = 1):
        self.slave = slave
        self.variant = variant if variant in VARIANTS else "21"
        self.lock = threading.Lock()
        self.cat = catalog
        self.eeprom: dict[tuple, int] = {}
        for p in catalog.params:
            if p.code in MISSING.get(self.variant, ()):
                continue
            v = p.default if p.default is not None else 0
            if p.model_dep and p.default is None:
                v = {1: 100, 2: 1500}.get(p.dec, 10) if p.g in (0, 8) else 0
            self.eeprom[(p.g, p.i)] = v & 0xFFFF
        for code, v in {**VARIANTS[self.variant], **EXTRA.get(self.variant, {})}.items():
            gi = parse_code(code)
            self.eeprom[gi] = v & 0xFFFF
        self.ram = dict(self.eeprom)
        # dynamic state
        self.status = D.ST_STOP
        self.cmd = D.CMD_STOP
        self.fault = 0
        self.freq = 0.0            # Hz, signed by direction
        self.setpoint = 0          # 0x1000, -10000..10000
        self.temp = 31.0
        self.load = 0.55
        self.last_rx = time.monotonic()
        self.last_tick = time.monotonic()
        self.on_min = 0.0
        self.run_min = 0.0
        self.kwh = 0.0

    # ----------------------------------------------------------------- helpers
    def p(self, code: str) -> int:
        return self.ram.get(parse_code(code), 0)

    def _sgn(self, v):
        return v - 65536 if v > 32767 else v

    def inject_fault(self, code: int):
        with self.lock:
            self.fault = code
            self.status = D.ST_STOP
            self.freq = 0.0

    # ----------------------------------------------------------------- physics
    def tick(self):
        now = time.monotonic()
        dt = min(now - self.last_tick, 0.5)
        self.last_tick = now
        timeout = self.p("PD-04") / 10.0
        if timeout > 0 and now - self.last_rx > timeout and self.fault == 0:
            self.fault = 16            # Err16, communication timeout
        fmax = self.p("P0-10") / 100.0 or 50.0
        if self.fault:
            self.status = D.ST_STOP
            self.freq = 0.0
        running = self.cmd in (D.CMD_FWD, D.CMD_REV, D.CMD_JOG_FWD, D.CMD_JOG_REV) and not self.fault
        if running:
            if self.cmd in (D.CMD_JOG_FWD, D.CMD_JOG_REV):
                target = self.p("P8-00") / 100.0
            elif self.p("P0-03") == D.P003_COMM:
                target = self.setpoint / 10000.0 * fmax
            else:
                target = self.p("P0-08") / 100.0
            hi = self.p("P0-12") / 100.0 or fmax
            lo = self.p("P0-14") / 100.0
            target = max(lo, min(hi, abs(target)))
            if self.cmd in (D.CMD_REV, D.CMD_JOG_REV):
                target = -target
            if self.p("P8-13") == 1 and target < 0:
                target = 0.0
        else:
            target = 0.0
        acc = max(self.p("P0-17") / 10.0, 0.1)
        dec = max(self.p("P0-18") / 10.0, 0.1)
        if self.cmd == D.CMD_COAST and not running:
            self.freq *= max(0.0, 1 - dt / 3.0)
            if abs(self.freq) < 0.2:
                self.freq = 0.0
        else:
            rate = fmax / (acc if abs(target) > abs(self.freq) else dec)
            step = rate * dt
            diff = target - self.freq
            self.freq += max(-step, min(step, diff))
        if running or abs(self.freq) > 0.01:
            self.status = D.ST_REV if (self.freq < 0 or self.cmd in (D.CMD_REV, D.CMD_JOG_REV)) else D.ST_FWD
        else:
            self.status = D.ST_STOP
        self.load = min(1.1, max(0.3, self.load + random.uniform(-0.01, 0.01)))
        rated_a = self.p("P1-03") / 100.0 or 5.0
        f = abs(self.freq)
        self.cur = 0.0 if f < 0.05 else rated_a * (0.32 + 0.6 * self.load * f / 50.0)
        heat = 31 + 28 * (self.cur / rated_a) ** 2
        self.temp += (heat - self.temp) * dt / 40.0
        self.on_min += dt / 60.0
        if self.status != D.ST_STOP:
            self.run_min += dt / 60.0

    def u0(self, idx: int) -> int:
        f = abs(self.freq)
        fmax = self.p("P0-10") / 100.0 or 50.0
        base = self.p("P1-04") / 100.0 or 50.0
        vmot = self.p("P1-02") or 380
        rated_a = self.p("P1-03") / 100.0 or 5.0
        cur = getattr(self, "cur", 0.0)
        vout = min(vmot, vmot * f / base) if f > 0.05 else 0
        kw = math.sqrt(3) * vout * cur * 0.82 / 1000.0
        decel = self.status != D.ST_STOP and f > 0.1 and self.cmd == D.CMD_STOP
        bus = 537.0 + random.uniform(-1.5, 1.5) + (28.0 if decel else 0.0) - 6.0 * cur / rated_a
        n = random.uniform(-0.6, 0.6)
        if self.p("P0-03") == D.P003_COMM:
            set_hz = self.setpoint / 10000.0 * fmax
        else:
            set_hz = self.p("P0-08") / 100.0
        vals = {
            0: f * 100, 1: abs(set_hz) * 100, 2: bus * 10, 3: vout,
            4: cur * (100 if self.p("PD-06") == 0 else 10),
            5: kw * 10, 6: (0 if f < 0.05 else (35 + 55 * self.load + n)) * 10,
            7: 0b0000101 if self.status != D.ST_STOP else 0b0000001,
            8: 0b0010 if self.status != D.ST_STOP else (0b0100 if self.fault else 0),
            9: 512 + int(30 * math.sin(time.monotonic() / 7)), 10: 0, 11: self.temp,
            12: 0, 13: 0, 14: f * 29.2, 15: 0, 16: 0, 17: 0, 18: 0, 19: f * 10,
            20: 0, 21: 5123, 22: 2, 23: int(3300 * min(1, f / fmax)),
            24: 0, 25: self.on_min, 26: self.run_min * 10, 27: 0,
            28: self.setpoint, 30: abs(set_hz) * 100, 31: 0,
            34: 0, 35: 0, 37: 312 + n * 10,
        }
        v = vals.get(idx)
        if v is None:
            return None
        return int(round(v)) & 0xFFFF

    # ----------------------------------------------------------------- Modbus
    def handle(self, req: bytes) -> bytes:
        if len(req) < 8:
            return b""
        lo, hi = crc16(req[:-2])
        if (req[-2], req[-1]) != (lo, hi) or req[0] != self.slave:
            return b""
        with self.lock:
            self.tick()                       # sees the silence before this frame
            self.last_rx = time.monotonic()
            fn = req[1]
            addr = (req[2] << 8) | req[3]
            val = (req[4] << 8) | req[5]
            if fn == 0x03:
                return self._read(addr, val)
            if fn == 0x06:
                return self._write(addr, val, req[:6])
            return self._exc(fn, 1)

    def _exc(self, fn: int, code: int) -> bytes:
        return with_crc(bytes([self.slave, fn | 0x80, code]))

    def _read_one(self, addr: int):
        hi = addr >> 8
        lo = addr & 0xFF
        if 0xF0 <= hi <= 0xFE and hi != 0xFF:
            g = hi - 0xF0
            if g == 0x0F:
                return None              # PP / PF is not reachable
            return self.ram.get((g, lo))
        if hi == 0x70:
            return self.u0(lo)
        if addr == D.REG_STATUS:
            return self.status
        if addr == D.REG_FAULT:
            return self.fault
        if addr == 0x8001:
            return 0
        if 0x1001 <= addr <= 0x1020:
            return self.u0(addr - 0x1001) if addr != 0x1007 else int(abs(self.freq) * 29.2)
        return None

    def _read(self, addr: int, count: int) -> bytes:
        if count < 1 or count > 12:
            return self._exc(0x03, 3)
        out = []
        for k in range(count):
            v = self._read_one(addr + k)
            if v is None:
                return self._exc(0x03, 2)
            out.append(v & 0xFFFF)
        body = bytes([self.slave, 0x03, 2 * count]) + b"".join(
            bytes([(v >> 8) & 0xFF, v & 0xFF]) for v in out)
        return with_crc(body)

    def _write(self, addr: int, val: int, echo: bytes) -> bytes:
        hi = addr >> 8
        lo = addr & 0xFF
        if addr == D.REG_CMD:
            if val not in range(1, 8):
                return self._exc(0x06, 3)
            if val == D.CMD_RESET:
                self.fault = 0
            elif self.fault:
                return self._exc(0x06, 4)
            elif self.p("P0-02") != D.P002_COMM:
                return self._exc(0x06, 4)
            else:
                self.cmd = val
            return with_crc(echo)
        if addr == D.REG_SETPOINT:
            s = self._sgn(val)
            if not -10000 <= s <= 10000:
                return self._exc(0x06, 3)
            self.setpoint = s
            return with_crc(echo)
        if 0x2001 <= addr <= 0x2004:
            return with_crc(echo)
        persistent = 0xF0 <= hi <= 0xFE
        ram_only = hi <= 0x0E
        if not (persistent or ram_only):
            return self._exc(0x06, 2)
        g = (hi - 0xF0) if persistent else hi
        key = (g, lo)
        if key not in self.ram:
            return self._exc(0x06, 2)
        code = "P%s-%02d" % ("0123456789ABCDEF"[g], lo)
        p = self.cat.get(code)
        if p is not None:
            if p.ro:
                return self._exc(0x06, 4)
            if p.stop_only and self.status != D.ST_STOP:
                return self._exc(0x06, 5)
            sv = self._sgn(val) if p.signed else val
            if p.min is not None and p.max is not None and not p.model_dep \
                    and not (p.min <= sv <= p.max):
                return self._exc(0x06, 3)
            if p.options and sv not in [o[0] for o in p.options]:
                return self._exc(0x06, 3)
        self.ram[key] = val
        if persistent:
            self.eeprom[key] = val
        return with_crc(echo)

    def power_cycle(self):
        with self.lock:
            self.ram = dict(self.eeprom)
            self.cmd = D.CMD_STOP
            self.status = D.ST_STOP
            self.freq = 0.0
            self.fault = 0


class SimSerial:
    """Enough of pyserial's Serial for modbus.Link."""

    def __init__(self, sim: SimDrive, latency: float = 0.003):
        self.sim = sim
        self.latency = latency
        self.buf = b""
        self.timeout = 0.3
        self.is_open = True

    def write(self, data: bytes):
        self.buf = self.sim.handle(bytes(data))
        if self.latency:
            time.sleep(self.latency + len(data) * 0.0002)
        return len(data)

    def read(self, n: int) -> bytes:
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    @property
    def in_waiting(self) -> int:
        return len(self.buf)

    def reset_input_buffer(self):
        self.buf = b""

    def reset_output_buffer(self):
        pass

    def close(self):
        self.is_open = False
