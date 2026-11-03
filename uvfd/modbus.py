# -*- coding: utf-8 -*-
"""
Modbus RTU over RS-485 - function 03 (read) and 06 (write).

Ported from VFDTool (vfdtool_core.Link), which was proven on real WSTG600
drives. Kept from there on purpose:

  * the CRC search tolerates ONE extra byte - some clones and PD-05=0 add it;
  * a READ with the right length but a broken CRC is accepted (cheap USB
    adapters corrupt timing); verifying a WRITE never accepts it;
  * at most 12 registers per request (manual, section 9).

New here: the control registers (0x1000 setpoint, 0x2000 command) are
reachable, but only through `write_control`, never through `write_reg`.
"""

from __future__ import annotations

import threading
import time

try:
    import serial
    import serial.tools.list_ports
except ImportError:                                     # pragma: no cover
    serial = None

CHUNK = 12

FORMATS = {           # PD-01 value -> (parity, stopbits)
    0: ("N", 2),
    1: ("E", 1),
    2: ("O", 1),
    3: ("N", 1),
}
BAUDS = [9600, 19200, 38400, 4800, 2400, 1200, 57600, 115200]
PD00_BAUDS = {0: 300, 1: 600, 2: 1200, 3: 2400, 4: 4800, 5: 9600, 6: 19200, 7: 38400,
              8: 57600, 9: 115200}


class MbError(Exception):
    """The drive answered with an exception code."""

    def __init__(self, code: int):
        super().__init__("exception %d" % code)
        self.code = code


class MbTimeout(Exception):
    """No answer, or an answer that could not be parsed."""


class MbBlocked(Exception):
    """The software refused the write before it reached the wire."""


EXC_TEXT = {
    "mk": {
        1: "лозинка / недозволена функција",
        2: "непостоечка адреса",
        3: "невалидна вредност (надвор од опсег)",
        4: "грешка при извршување",
        5: "параметарот не може да се менува сега (запри го моторот)",
        6: "фреквентниот е зафатен",
        7: "заклучено (PP лозинка)",
        8: "грешка при запис во EEPROM",
    },
    "en": {
        1: "password / illegal function",
        2: "invalid address",
        3: "invalid value (out of range)",
        4: "execution error",
        5: "parameter cannot be changed now (stop the motor)",
        6: "drive is busy",
        7: "locked (PP password)",
        8: "EEPROM write error",
    },
}


def exc_text(code: int, lang: str = "mk") -> str:
    return EXC_TEXT.get(lang, EXC_TEXT["en"]).get(code, "?")


def crc16(data: bytes) -> tuple[int, int]:
    """Modbus CRC16; (low, high) - the low byte goes on the wire first."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc & 0xFF, (crc >> 8) & 0xFF


def with_crc(frame: bytes) -> bytes:
    lo, hi = crc16(frame)
    return frame + bytes([lo, hi])


def list_ports() -> list[tuple[str, str]]:
    """[(device, description)] of the serial ports present right now."""
    if serial is None:
        return []
    out = []
    for p in serial.tools.list_ports.comports():
        out.append((p.device, p.description or ""))
    return sorted(out, key=lambda t: (len(t[0]), t[0]))


# Addresses the generic write must never touch: run/stop, setpoint, status,
# monitoring, fault. They go through `write_control` only.
CONTROL_HI = (0x10, 0x20, 0x30, 0x70, 0x80)


class Link:
    """
    One serial port, one drive address at a time. NOT thread safe by itself:
    the bus worker is the only caller (single master on the bus).
    """

    def __init__(self):
        self.ser = None
        self.port = ""
        self.baud = 9600
        self.parity = "N"
        self.stopbits = 2
        self.slave = 1
        self.gap = 0.012             # idle time between frames (> 3.5 chars)
        self.stats = {"tx": 0, "ok": 0, "err": 0, "timeouts": 0, "rx": 0, "echo": 0}
        self.abort = threading.Event()

    # ----------------------------------------------------------------- open / close
    def open(self, port: str, baud: int = 9600, parity: str = "N", stopbits: int = 2,
             slave: int = 1, timeout: float = 0.35, serial_obj=None):
        self.port, self.baud, self.parity = port, baud, parity
        self.stopbits, self.slave = stopbits, slave
        self.gap = max(0.006, 40.0 / baud)
        if serial_obj is not None:                    # simulator / tests
            self.ser = serial_obj
            return
        if serial is None:                            # pragma: no cover
            raise MbTimeout("pyserial is missing")
        timeout = max(timeout, 400.0 / baud + 0.12)
        self.ser = serial.Serial(
            port=port, baudrate=baud, bytesize=8,
            parity={"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN, "O": serial.PARITY_ODD}[parity],
            stopbits=serial.STOPBITS_TWO if stopbits == 2 else serial.STOPBITS_ONE,
            timeout=timeout, inter_byte_timeout=0.04, write_timeout=1.0)
        time.sleep(0.12)              # some USB adapters need a moment
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()

    def close(self):
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None

    @property
    def is_open(self) -> bool:
        return self.ser is not None and getattr(self.ser, "is_open", True)

    def describe(self) -> str:
        return "%s %d 8%s%d #%d" % (self.port, self.baud, self.parity, self.stopbits, self.slave)

    # ----------------------------------------------------------------- frames
    def _xfer(self, req: bytes, expect: int) -> bytes:
        if self.abort.is_set():
            raise MbTimeout("aborted")
        if self.ser is None:
            raise MbTimeout("port closed")
        self.stats["tx"] += 1
        self.ser.reset_input_buffer()
        self.ser.write(req)
        # inter_byte_timeout ends a short (exception) answer early
        raw = self.ser.read(expect)
        # for the connection diagnosis: did anything come back at all, and was
        # it only our own request echoed by the adapter?
        self.stats["rx"] += len(raw)
        if len(raw) >= 6 and raw[:6] == req[:6]:
            self.stats["echo"] += len(raw)          # bytes that were only our own request
        if len(raw) == expect and not (raw[1] & 0x80):
            lo, hi = crc16(raw[:-2])
            if (raw[-2], raw[-1]) != (lo, hi):
                # one stray byte in front (clones, PD-05=0): pick up the tail
                raw += self._read_tail()
        time.sleep(self.gap)
        return raw

    def _read_tail(self) -> bytes:
        old = getattr(self.ser, "timeout", None)
        try:
            if old is not None:
                self.ser.timeout = 0.05
            return self.ser.read(2)
        finally:
            if old is not None:
                self.ser.timeout = old

    def read_regs(self, addr: int, count: int) -> list[int]:
        """Function 03. Raises MbError / MbTimeout."""
        req = with_crc(bytes([self.slave, 0x03, (addr >> 8) & 0xFF, addr & 0xFF,
                              (count >> 8) & 0xFF, count & 0xFF]))
        raw = self._xfer(req, 5 + 2 * count)
        try:
            vals = self._parse_read(raw, count, strict=False)
        except MbTimeout:
            self.stats["timeouts" if len(raw) < 5 else "err"] += 1
            raise
        except MbError:
            self.stats["err"] += 1
            raise
        self.stats["ok"] += 1
        return vals

    def read_strict(self, addr: int) -> int:
        """One register; the CRC must match exactly (write verification)."""
        req = with_crc(bytes([self.slave, 0x03, (addr >> 8) & 0xFF, addr & 0xFF, 0, 1]))
        raw = self._xfer(req, 7)
        return self._parse_read(raw, 1, strict=True)[0]

    def _parse_read(self, raw: bytes, count: int, strict: bool) -> list[int]:
        if len(raw) >= 5 and raw[1] == 0x83:
            lo, hi = crc16(raw[:3])
            if raw[3] == lo and raw[4] == hi or not strict:
                raise MbError(raw[2])
        if len(raw) < 5:
            raise MbTimeout("no answer")
        want = 3 + 2 * count
        for start in (0, 1):
            for end in (want, want + 1, want + 2):
                if start + end + 2 > len(raw):
                    continue
                frame = raw[start:start + end]
                lo, hi = crc16(frame)
                if raw[start + end] == lo and raw[start + end + 1] == hi \
                        and frame[1] == 0x03 and frame[2] >= 2 * count:
                    return self._values(frame, count)
        if not strict and len(raw) >= want and raw[1] == 0x03 and raw[2] == 2 * count:
            return self._values(raw[:want], count)
        raise MbTimeout("bad answer (CRC)")

    @staticmethod
    def _values(frame: bytes, count: int) -> list[int]:
        data = frame[3:3 + frame[2]]
        return [(data[2 * i] << 8) | data[2 * i + 1] for i in range(count)]

    def _write06(self, addr: int, val: int):
        val &= 0xFFFF
        req = with_crc(bytes([self.slave, 0x06, (addr >> 8) & 0xFF, addr & 0xFF,
                              (val >> 8) & 0xFF, val & 0xFF]))
        raw = self._xfer(req, 8)
        if len(raw) >= 5 and raw[1] == 0x86:
            self.stats["err"] += 1
            raise MbError(raw[2])
        if len(raw) < 8:
            self.stats["timeouts"] += 1
            raise MbTimeout("no answer")
        for s in (0, 1):
            if len(raw) >= s + 8:
                lo, hi = crc16(raw[s:s + 6])
                if raw[s + 6] == lo and raw[s + 7] == hi and raw[s:s + 6] == req[:6]:
                    self.stats["ok"] += 1
                    return
        self.stats["err"] += 1
        raise MbTimeout("the answer does not echo the request")

    def write_reg(self, addr: int, val: int):
        """
        Parameter write. GUARD: control/monitor registers are refused here -
        writing 1 to 0x2000 spins the motor, so that goes through
        `write_control` only, which the UI calls from explicit buttons.
        """
        if ((addr >> 8) & 0xFF) in CONTROL_HI:
            raise MbBlocked("control register")
        self._write06(addr, val)

    def write_control(self, addr: int, val: int):
        """0x1000 setpoint, 0x2000 command, 0x2001.. outputs. Nothing else."""
        if not (0x1000 <= addr <= 0x1000 or 0x2000 <= addr <= 0x2004):
            raise MbBlocked("not a control register")
        self._write06(addr, val)
