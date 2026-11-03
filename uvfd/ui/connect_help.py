# -*- coding: utf-8 -*-
"""
"Connection help" - everything needed to get the PC talking to the drive:
wiring, what each PD parameter does and what it must hold, what 8N2 means
and where it is set, keypad steps, the ports on this computer, a checklist,
plus "Find drive" (every baud / format / address) and "Factory link".

Sources: WSTG600 manual 9.7 (PD group) and the SU-650 manual's PD table -
both drives ship with PD-00 = 5 (9600), PD-01 = 0 (8N2), PD-02 = 1,
PD-05 = 1 (standard Modbus); the SU650 also has PD-08 master/slave = 0.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from .. import i18n
from ..i18n import tr
from ..modbus import list_ports
from . import theme as th
from .common import btn, label


def _mk() -> bool:
    return i18n.lang() == "mk"


def _t(mk: str, en: str) -> str:
    return mk if _mk() else en


def _table(head: list[str], rows: list[list[str]], hl_col: int | None = None) -> str:
    cell = "padding:6px 10px; border-bottom:1px solid %s;" % th.BORDER
    h = "".join("<th align='left' style='%s color:%s; font-weight:600'>%s</th>" % (cell, th.MUTED, x) for x in head)
    body = ""
    for r in rows:
        tds = []
        for c, x in enumerate(r):
            col = th.ACCENT if c == hl_col else (th.TEXT if c == 0 else th.MUTED)
            weight = "700" if c in (0, hl_col) else "400"
            tds.append("<td style='%s color:%s; font-weight:%s'>%s</td>" % (cell, col, weight, x))
        body += "<tr>%s</tr>" % "".join(tds)
    return "<table cellspacing='0' width='100%%'><tr>%s</tr>%s</table>" % (h, body)


def _card(title: str, html: str) -> QFrame:
    f = QFrame()
    f.setObjectName("Card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(18, 14, 18, 16)
    lay.setSpacing(8)
    lay.addWidget(label(title.upper(), "CardTitle"))
    body = QLabel(html)
    body.setTextFormat(Qt.RichText)
    body.setWordWrap(True)
    body.setFont(th.font(9.5))
    body.setStyleSheet("color:%s;" % th.MUTED)
    body.setTextInteractionFlags(Qt.TextSelectableByMouse)
    lay.addWidget(body)
    lay.addStretch(1)
    return f


def wiring_html() -> str:
    rows = [["A (D+)", "→", "485+"], ["B (D−)", "→", "485−"], ["GND", "→", "COM / PE " + _t("(ако адаптерот има)", "(if the adapter has it)")]]
    return (_table([_t("Адаптер", "Adapter"), "", _t("Фреквентен", "Drive")], rows, hl_col=2)
            + "<p style='margin-top:10px'>" + _t(
                "<b style='color:%s'>Нема одговор? Прво замени ги A и B</b> — многу адаптери се обележани "
                "обратно, а со замената ништо не се оштетува.<br>Користи усукан пар (UTP), подалеку од "
                "моторните кабли. Над ~30 m стави 120 Ω помеѓу 485+ и 485− на крајот од линијата. "
                "485 клемите се на управувачката плочка, никогаш на 220/380 V." % th.AMBER,
                "<b style='color:%s'>No answer? Swap A and B first</b> — many adapters are labelled the "
                "other way round, and swapping damages nothing.<br>Use twisted pair (UTP), away from motor "
                "cables. Above ~30 m put 120 Ω between 485+ and 485− at the end of the line. The 485 "
                "terminals are on the control board, never on 220/380 V." % th.AMBER) + "</p>")


def pd_html() -> str:
    f = _t("фабрички", "factory")
    rows = [
        ["PD-00", _t("Брзина (baud)", "Baud rate"), "5 = 9600",
         "5", _t("Брзина: 9600. Ако дисплејот покажува 6005 или 5005 — важи последната цифра (5).",
                 "Baud: 9600. If the display shows 6005 or 5005, the last digit counts (5).")],
        ["PD-01", _t("Формат на податоци", "Data format"), "0 = 8N2",
         "0", _t("Формат: 8N2", "Format: 8N2")],
        ["PD-02", _t("Адреса на фреквентниот", "Drive address"), "1",
         "1", _t("Адреса #1. Секој фреквентен на ист кабел мора да има различна.",
                 "Address #1. Each drive on the same cable needs a different one.")],
        ["PD-03", _t("Доцнење на одговор", "Response delay"), "2 ms", "2", _t("остави", "leave it")],
        ["PD-04", _t("Timeout на комуникација", "Communication timeout"), "0.0 s",
         "0.0", _t("остави — UVFD сама го поставува (само во RAM) кога вклучуваш PC управување",
                   "leave it — UVFD sets it itself (RAM only) when you turn on PC control")],
        ["PD-05", _t("Протокол", "Protocol"), "1 = Modbus",
         "1", _t("мора 1 (стандарден Modbus). Ако покажува 31 — важи последната цифра.",
                 "must be 1 (standard Modbus). If it shows 31, the last digit counts.")],
        ["PD-06", _t("Резолуција на струја", "Current resolution"), "0 = 0.01 A", "0", _t("остави", "leave it")],
        ["PD-08", _t("Master / Slave (само SU650)", "Master / Slave (SU650 only)"), "0 = Slave",
         "0", _t("мора 0 — на 1 (Master) фреквентниот не одговара на PC", "must be 0 — at 1 (Master) the drive ignores the PC")],
    ]
    return _table(["", _t("Што е", "What it is"), f.capitalize(), _t("Треба", "Needs"), _t("Во UVFD / забелешка", "In UVFD / note")],
                  rows, hl_col=3)


def format_html() -> str:
    rows = [["0", "8N2", _t("8 бита · без паритет · 2 стоп бита", "8 bits · no parity · 2 stop bits") + "  ← " +
             _t("фабрички", "factory")],
            ["1", "8E1", _t("8 бита · парен паритет · 1 стоп бит", "8 bits · even parity · 1 stop bit")],
            ["2", "8O1", _t("8 бита · непарен паритет · 1 стоп бит", "8 bits · odd parity · 1 stop bit")],
            ["3", "8N1", _t("8 бита · без паритет · 1 стоп бит", "8 bits · no parity · 1 stop bit")]]
    return (_t("<p>„8N2“ не се пишува никаде — тоа е <b style='color:%s'>бројот 0 во параметарот PD-01</b>. "
               "Фреквентниот од фабрика е веќе на 0 = 8N2, а UVFD стандардно е на 8N2, па <b>на фабрички "
               "фреквентен не треба ништо да менуваш</b>.</p>" % th.TEXT,
               "<p>“8N2” is not typed anywhere — it is <b style='color:%s'>the number 0 in parameter PD-01</b>. "
               "The drive ships at 0 = 8N2 and UVFD defaults to 8N2, so <b>on a factory drive nothing needs "
               "changing</b>.</p>" % th.TEXT)
            + _table(["PD-01", _t("Во UVFD", "In UVFD"), _t("Значење", "Meaning")], rows, hl_col=1))


def keypad_html() -> str:
    steps = _t([
        "Притисни <b>PRG</b> — се појавува група (P0, P1 …).",
        "Со <b>▲ / ▼</b> оди до групата <b>Pd</b>.",
        "<b>ENTER</b> — се покажува <b>Pd-00</b>.",
        "Со <b>▲ / ▼</b> избери го параметарот (на пр. <b>Pd-01</b>) и притисни <b>ENTER</b> — вредноста трепка.",
        "Со <b>▲ / ▼</b> смени ја цифрата, со <b>&gt;&gt;</b> (SHIFT) оди на следната цифра.",
        "<b>ENTER</b> = зачувај (оди на следниот параметар). <b>PRG</b> = излез без зачувување.",
        "Ако по промена на PD-00/PD-01 нема врска, исклучи и вклучи го фреквентниот.",
    ], [
        "Press <b>PRG</b> — a group is shown (P0, P1 …).",
        "Use <b>▲ / ▼</b> to reach group <b>Pd</b>.",
        "<b>ENTER</b> — <b>Pd-00</b> is shown.",
        "Pick the parameter with <b>▲ / ▼</b> (e.g. <b>Pd-01</b>) and press <b>ENTER</b> — the value blinks.",
        "Change the digit with <b>▲ / ▼</b>, move to the next digit with <b>&gt;&gt;</b> (SHIFT).",
        "<b>ENTER</b> = save (moves to the next parameter). <b>PRG</b> = leave without saving.",
        "If there is no link after changing PD-00/PD-01, power the drive off and on.",
    ])
    lis = "".join("<li style='margin-bottom:5px'>%s</li>" % s for s in steps)
    ex = _t("Пример за 8N2, 9600, адреса 1: Pd-00 = 5, Pd-01 = 0, Pd-02 = 1, Pd-05 = 1.",
            "Example for 8N2, 9600, address 1: Pd-00 = 5, Pd-01 = 0, Pd-02 = 1, Pd-05 = 1.")
    return ("<ol style='margin-left:-18px'>%s</ol><p style='color:%s'><b>%s</b></p>" % (lis, th.ACCENT, ex)
            + _t("<p>Ако е поставена лозинка (PP-00), прво отклучи ја од тастатурата.</p>",
                 "<p>If a password is set (PP-00), unlock it from the keypad first.</p>"))


def ports_html() -> str:
    ports = list_ports()
    if not ports:
        return _t("<p style='color:%s'><b>Нема ниедна COM порта.</b> Вклучи го USB-RS485 адаптерот. "
                  "Ефтините (CH340/CH341) бараат драјвер; FTDI и CP2102 работат веднаш.</p>" % th.AMBER,
                  "<p style='color:%s'><b>No COM port at all.</b> Plug in the USB-RS485 adapter. Cheap ones "
                  "(CH340/CH341) need a driver; FTDI and CP2102 work out of the box.</p>" % th.AMBER)
    rows = [[dev, desc.replace("(%s)" % dev, "").strip() or "—"] for dev, desc in ports]
    return (_table([_t("Порта", "Port"), _t("Уред", "Device")], rows)
            + _t("<p style='margin-top:8px'>Не знаеш која е? Извади го адаптерот, отвори ја листата на порти и види која исчезнала.</p>",
                 "<p style='margin-top:8px'>Not sure which one? Unplug the adapter, open the port list and see which one disappeared.</p>"))


def checklist_html() -> str:
    items = _t([
        "Фреквентниот е вклучен (моторот не мора да работи).",
        "Избрана е вистинската порта; ниедна друга програма (VFDTool) не ја држи.",
        "A и B — пробај и заменети.",
        "На дисплејот: Pd-00 последна цифра 5, Pd-01 = 0, Pd-02 = адресата во UVFD, Pd-05 = 1.",
        "SU650: Pd-08 = 0 (Slave).",
        "Не знаеш што е поставено? Притисни „Пребарај фреквентен“ — ги пробува сите брзини, формати и адреси 1–10.",
    ], [
        "The drive is powered (the motor does not have to run).",
        "The right port is selected; no other program (VFDTool) holds it.",
        "A and B — try them swapped.",
        "On the display: Pd-00 last digit 5, Pd-01 = 0, Pd-02 = the address in UVFD, Pd-05 = 1.",
        "SU650: Pd-08 = 0 (Slave).",
        "Not sure what is set? Press “Find drive” — it tries every baud, format and address 1–10.",
    ])
    return "".join("<p style='margin:0 0 6px 0'><span style='color:%s'>☐</span>&nbsp; %s</p>" % (th.ACCENT, s)
                   for s in items)


class ConnectHelpDialog(QDialog):
    def __init__(self, parent, on_search=None, on_factory=None):
        super().__init__(parent)
        self.setObjectName("Root")
        self.setWindowTitle(tr("conn_help"))
        pw = parent.size() if parent else None
        self.resize(min(1180, int(pw.width() * 0.9)) if pw else 1100, int(pw.height() * 0.9) if pw else 820)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 18, 22, 16)
        v.setSpacing(12)
        v.addWidget(label(tr("conn_help"), font=th.font(15, 700, display=True)))
        sub = label(_t("Фабрички фреквентен = <b>9600 · 8N2 · адреса 1</b>, а UVFD е поставена исто. "
                       "На фабрички фреквентен треба само правилно ожичување.",
                       "A factory drive = <b>9600 · 8N2 · address 1</b>, and UVFD is set the same. "
                       "A factory drive only needs correct wiring."), "Muted", wrap=True)
        sub.setTextFormat(Qt.RichText)
        v.addWidget(sub)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        g = QGridLayout(inner)
        g.setContentsMargins(0, 0, 8, 0)
        g.setSpacing(12)
        g.addWidget(_card(_t("1 · Ожичување", "1 · Wiring"), wiring_html()), 0, 0)
        g.addWidget(_card(_t("2 · 8N2 — што е и каде се поставува", "2 · 8N2 — what it is and where it is set"),
                          format_html()), 0, 1)
        g.addWidget(_card(_t("3 · PD параметри на фреквентниот (група Pd)", "3 · PD parameters on the drive (group Pd)"),
                          pd_html()), 1, 0, 1, 2)
        g.addWidget(_card(_t("4 · Поставување од тастатура", "4 · Setting it from the keypad"), keypad_html()), 2, 0)
        right = QVBoxLayout()
        right.setSpacing(12)
        right.addWidget(_card(_t("5 · Порти на овој компјутер", "5 · Ports on this computer"), ports_html()))
        right.addWidget(_card(_t("6 · Ако пак не се поврзува", "6 · Still no connection"), checklist_html()))
        g.addLayout(right, 2, 1)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(1, 1)
        area.setWidget(inner)
        v.addWidget(area, 1)

        row = QHBoxLayout()
        if on_search:
            b = btn("⌕  " + tr("find_drive"), "primary", tr("find_drive_tip"))
            b.clicked.connect(lambda: (self.accept(), on_search()))
            row.addWidget(b)
        if on_factory:
            b = btn(tr("factory_link"), "", tr("factory_link_tip"))
            b.clicked.connect(lambda: (on_factory(), self.accept()))
            row.addWidget(b)
        row.addStretch(1)
        c = btn(tr("close"))
        c.clicked.connect(self.reject)
        row.addWidget(c)
        v.addLayout(row)
