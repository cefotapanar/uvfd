# -*- coding: utf-8 -*-
"""
What the WSTG600 / SU650 drive exposes over Modbus (manual, section 9.6.4).

    F000 | group<<8 | index   parameters, read + persistent (EEPROM) write
    0000 | group<<8 | index   the same parameters, RAM-only write
    7000 | index              U0 monitoring group (read only)
    1000                      communication setpoint, -10000..10000 = % of P0-10
    2000                      command: 1 FWD, 2 REV, 3 JOG FWD, 4 JOG REV,
                              5 coast stop, 6 decelerate to stop, 7 fault reset
    3000                      status: 1 FWD, 2 REV, 3 stopped
    8000                      current fault code

The PF/PP group is not reachable over communication (and PP-01 = 1 erases
every parameter), so it is never touched.
"""

from __future__ import annotations

from dataclasses import dataclass, field

REG_SETPOINT = 0x1000
REG_CMD = 0x2000
REG_STATUS = 0x3000
REG_FAULT = 0x8000
REG_U0 = 0x7000

CMD_FWD, CMD_REV, CMD_JOG_FWD, CMD_JOG_REV = 1, 2, 3, 4
CMD_COAST, CMD_STOP, CMD_RESET = 5, 6, 7

ST_FWD, ST_REV, ST_STOP = 1, 2, 3

# P0-02 command source / P0-03 frequency source values for PC control
P002_PANEL, P002_TERMINAL, P002_COMM = 0, 1, 2
P003_COMM = 9

# --------------------------------------------------------------------------- U0 map
# index, key, mk, en, decimals, unit, signed

@dataclass(frozen=True)
class Mon:
    idx: int
    key: str
    mk: str
    en: str
    dec: int = 0
    unit: str = ""
    signed: bool = False

    def title(self, lang: str) -> str:
        return self.mk if lang == "mk" else self.en


MONITOR = [
    Mon(0, "run_hz", "Излезна фреквенција", "Output frequency", 2, "Hz"),
    Mon(1, "set_hz", "Зададена фреквенција", "Set frequency", 2, "Hz"),
    Mon(2, "dc_bus", "DC напон", "DC bus voltage", 1, "V"),
    Mon(3, "out_v", "Излезен напон", "Output voltage", 0, "V"),
    Mon(4, "out_a", "Излезна струја", "Output current", 2, "A"),
    Mon(5, "out_kw", "Излезна моќност", "Output power", 1, "kW"),
    Mon(6, "torque", "Вртежен момент", "Output torque", 1, "%", True),
    Mon(7, "di", "DI влезови", "DI inputs"),
    Mon(8, "do", "DO излези", "DO outputs"),
    Mon(9, "ai1", "AI1 напон", "AI1 voltage", 2, "V", True),
    Mon(10, "ai2", "AI2 напон", "AI2 voltage", 2, "V", True),
    Mon(11, "temp", "Температура на ладилник", "Heatsink temperature", 0, "°C"),
    Mon(12, "count", "Бројач", "Count value"),
    Mon(13, "length", "Должина", "Length", 0, "m"),
    Mon(14, "load_speed", "Брзина на товар", "Load speed"),
    Mon(15, "pid_set", "PID зададено", "PID setpoint"),
    Mon(16, "pid_fb", "PID повратна врска", "PID feedback"),
    Mon(17, "plc_step", "PLC чекор", "PLC step"),
    Mon(18, "hdi_khz", "HDI импулси", "HDI pulse frequency", 2, "kHz"),
    Mon(19, "fb_hz", "Повратна брзина", "Feedback speed", 1, "Hz"),
    Mon(20, "remain_min", "Преостанато време", "Remaining run time", 1, "min"),
    Mon(21, "ai1_raw", "AI1 пред калибрација", "AI1 before calibration", 3, "V", True),
    Mon(22, "ai2_raw", "AI2 пред калибрација", "AI2 before calibration", 3, "V", True),
    Mon(23, "pot_raw", "Потенциометар (AI3)", "Potentiometer (AI3)", 3, "V", True),
    Mon(24, "line_speed", "Линиска брзина", "Linear speed", 0, "m/min"),
    Mon(25, "on_min", "Вклучен од старт", "Power-on time (this run)", 0, "min"),
    Mon(26, "run_min", "Работи од старт", "Running time (this run)", 1, "min"),
    Mon(27, "hdi_hz", "HDI импулси", "HDI pulse frequency", 0, "Hz"),
    Mon(28, "comm_pct", "Комуникациска вредност", "Communication setpoint", 2, "%", True),
    Mon(30, "freq_x", "Главна фреквенција X", "Main frequency X", 2, "Hz"),
    Mon(31, "freq_y", "Помошна фреквенција Y", "Auxiliary frequency Y", 2, "Hz"),
    Mon(34, "motor_temp", "Температура на мотор", "Motor temperature", 0, "°C"),
    Mon(35, "target_torque", "Целен момент", "Target torque", 1, "%", True),
    Mon(37, "pf_angle", "Агол на фактор на моќност", "Power factor angle", 1, "°"),
]
MON_BY_KEY = {m.key: m for m in MONITOR}
MON_BY_IDX = {m.idx: m for m in MONITOR}

FAST_BLOCK = (0, 12)            # U0-00..U0-11, one request
SLOW_BLOCKS = [(12, 12), (24, 5), (30, 2)]
SLOW_SINGLES = [34, 35, 37]

# U0-07 / U0-08 bit layout (manual, U0 group)
DI_BITS = ["DI1", "DI2", "DI3", "DI4", "DI5", "DI6", "DI7"]
DO_BITS = ["DO3", "RY1", "RY2", "DO1", "DO2"]

# Parameters read on connect and refreshed now and then: identity, the basic
# settings shown on the main screen, and the totals.
IDENTITY = ["P7-10", "P7-11", "P0-00", "P1-01", "P1-02", "P7-08"]
BASICS = ["P0-02", "P0-03", "P0-10", "P0-12", "P0-14", "P0-17", "P0-18",
          "P6-10", "P8-13", "P1-03", "P1-04", "P1-05", "PD-04", "PD-06", "P0-22"]
TOTALS = ["P7-09", "P7-13", "P7-14", "P9-14", "P9-15", "P9-16"]


# --------------------------------------------------------------------------- faults

FAULTS = {
    0: ("Нема грешка", "No fault"),
    2: ("Прекуструја при забрзување", "Overcurrent during acceleration"),
    3: ("Прекуструја при успорување", "Overcurrent during deceleration"),
    4: ("Прекуструја при константна брзина", "Overcurrent at constant speed"),
    5: ("Пренапон при забрзување", "Overvoltage during acceleration"),
    6: ("Пренапон при успорување", "Overvoltage during deceleration"),
    7: ("Пренапон при константна брзина", "Overvoltage at constant speed"),
    9: ("Поднапон", "Undervoltage"),
    10: ("Преоптоварување на фреквентниот", "Inverter overload"),
    11: ("Преоптоварување на моторот", "Motor overload"),
    12: ("Испадната фаза на влез", "Input phase loss"),
    13: ("Испадната фаза на излез", "Output phase loss"),
    14: ("Прегреан модул", "Module overheat"),
    15: ("Надворешна грешка", "External fault"),
    16: ("Грешка во комуникација", "Communication fault"),
    17: ("Грешка на контактор", "Contactor fault"),
    18: ("Грешка при мерење струја", "Current detection fault"),
    19: ("Грешка при автотјунинг на моторот", "Motor autotuning fault"),
    21: ("Грешка при читање/запис на параметри", "Parameter read/write fault"),
    22: ("Хардверска грешка на фреквентниот", "Inverter hardware fault"),
    23: ("Краток спој на моторот кон земја", "Motor short circuit to ground"),
    26: ("Истечено работно време", "Running time reached"),
    27: ("Корисничка грешка 1", "User-defined fault 1"),
    28: ("Корисничка грешка 2", "User-defined fault 2"),
    29: ("Истечено време вклучен", "Power-on time reached"),
    30: ("Растоварено (без товар)", "Off load"),
    31: ("Изгубена PID повратна врска", "PID feedback lost while running"),
    40: ("Брзо ограничување на струја - истечено", "Fast current limit timeout"),
    42: ("Преголема разлика во брзина", "Speed deviation too large"),
    43: ("Пребрз мотор", "Motor over-speed"),
}


def fault_text(code: int | None, lang: str = "mk") -> str:
    if code is None:
        return ""
    t = FAULTS.get(code)
    if t is None:
        return ("Грешка %d" if lang == "mk" else "Fault %d") % code
    return t[0] if lang == "mk" else t[1]


def fault_code_label(code: int) -> str:
    return "E-%02d" % code


# --------------------------------------------------------------------------- identity

@dataclass
class Identity:
    model: int = -1          # P7-10, shown as model/100 ("2.09")
    sw: int = -1             # P7-11, the BIOS / software version
    gp: int = -1             # P0-00, 1 = G (constant torque), 2 = P (fan/pump)
    power: int = -1          # P1-01, 0.1 kW
    voltage: int = -1        # P1-02, V
    inv_volt: int = -1       # P7-08

    @property
    def bios_key(self) -> str:
        return str(self.sw) if self.sw >= 0 else "?"

    @property
    def model_text(self) -> str:
        return "%.2f" % (self.model / 100.0) if self.model >= 0 else "?"

    @property
    def power_text(self) -> str:
        return ("%.1f kW" % (self.power / 10.0)).replace(".0 kW", " kW") if self.power > 0 else ""

    @classmethod
    def from_values(cls, vals: dict) -> "Identity":
        def v(code):
            x = vals.get(code)
            return -1 if x is None else x
        return cls(model=v("P7-10"), sw=v("P7-11"), gp=v("P0-00"), power=v("P1-01"),
                   voltage=v("P1-02"), inv_volt=v("P7-08"))


@dataclass
class Snapshot:
    """One monitoring poll, as the bus worker hands it to the screen."""
    t: float = 0.0
    ok: bool = False
    status: int = -1                      # 1 FWD, 2 REV, 3 stopped
    fault: int = 0
    u0: dict = field(default_factory=dict)          # idx -> raw
    error: str = ""

    def running(self) -> bool:
        return self.status in (ST_FWD, ST_REV)
