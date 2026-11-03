# -*- coding: utf-8 -*-
"""
Version of UVFD.

New version: raise VERSION, write CHANGES (newest first), then
`python build.py --release`. Every running UVFD sees the new GitHub release
and offers the update.
"""

VERSION = "1.3.0"

#: GitHub repository the updater reads releases from (must be public).
REPO = "cefotapanar/uvfd"

#: Shown in the "New version" window of OLDER installations. Newest first;
#: earlier entries keep their version tag, so a jump over several versions
#: still shows everything.
CHANGES = {
    "mk": [
        "Копче „Фабрички“ (во Основни подесувања): вистинскиот ресет на фреквентниот преку кабелот (PP-01 на "
        "0x1F01): фабрички без моторот, со моторот (SU650) или само бришење на историјата на грешки. Пред тоа "
        "сегашните поставки се зачувуваат како профил; по ресетот UVFD сама се поврзува на 9600 · 8N2 · #1.",
        "Панел „Фреквентен“ (долу десно): број на модел (P7-10), BIOS, тип G/P, напојување од DC напонот, "
        "номинален напон (P7-08), температура на IGBT модулот (P7-07) и податоците на моторот. Ознака на "
        "моделот (на пр. G600-4T45G · 45 kW) се поставува еднаш од табелата на модели (77 модели од "
        "упатствата) и потоа се гледа горе за секој фреквентен со ист број на модел.",
        "(1.2.0) „Прекини“ (и затворање на програмата): ако PC управувањето го вклучи UVFD на тој фреквентен, прашува "
        "дали да го врати претходниот режим (P0-02 и P0-03 какви што биле). Ако моторот работи, прво го запира. "
        "Ако фреквентниот веќе бил во PC режим, не прашува ништо.",
        "(1.1.2) „Пребарај фреквентен“: „Откажи“ и X среде пребарување сега го затвораат прозорецот и програмата "
        "веднаш е слободна; откажувањето се јавува мирно, не како црвена грешка.",
        "(1.1.1) Поправено: прозорецот за напредок (Скенирај BIOS, Прочитај, Пребарај фреквентен) се заглавуваше "
        "на 100% и не се затвораше ни со X. Сега се затвора сам кога ќе заврши, а X/Esc/Откажи ја прекинуваат "
        "работата и го затвораат.",
        "(1.1.0) Помош за поврзување (копче „Помош“ до „Поврзи“): ожичување, сите PD параметри што се за што и што "
        "треба да стои на фреквентниот, што е 8N2 и дека е PD-01 = 0, поставување од тастатура чекор по "
        "чекор, порти на компјутерот и листа за проверка.",
        "(1.1.0) „Пребарај фреквентен“: ги пробува сите брзини, формати и адреси 1–10. Ако не најде, кажува што е "
        "проблемот: нема никаков сигнал (жици/порта), адаптерот враќа само ехо, или брзината/форматот не се исти.",
        "(1.1.0) Врската стандардно е фабричката на фреквентните: 9600 · 8N2 · адреса 1 (PD-00=5, PD-01=0, PD-02=1). "
        "Постоечките инсталации еднаш се префрлаат на неа.",
        "(1.1.0) Листата на порти се освежува сама кога ќе се отвори.",
        "(1.0.0) Прва верзија: мониторинг во живо, старт/стоп и Hz преку RS-485, подесувања по "
        "категории со пребарување, Read/Load на сите параметри, следење на BIOS верзии.",
    ],
    "en": [
        "“Factory” button (in Basic settings): the drive's own reset over the cable (PP-01 at 0x1F01): factory "
        "without the motor, with the motor (SU650) or only clearing the fault history. The current settings are "
        "saved as a profile first; afterwards UVFD reconnects at 9600 · 8N2 · #1.",
        "“Drive” panel (bottom right): model number (P7-10), BIOS, G/P type, supply from the DC bus, rated "
        "voltage (P7-08), IGBT module temperature (P7-07) and the motor data. A model label (e.g. G600-4T45G · "
        "45 kW) is set once from the model table (77 models from the manuals) and then shown at the top for "
        "every drive with the same model number.",
        "(1.2.0) “Disconnect” (and closing the program): if UVFD turned PC control on for that drive, it asks whether "
        "to restore the previous mode (P0-02 and P0-03 as they were), stopping the motor first if it runs. "
        "If the drive was already in PC mode, nothing is asked.",
        "(1.1.2) “Find drive”: Cancel and X during a search now close the window and free the program at once; "
        "a cancel is reported quietly, not as a red error.",
        "(1.1.1) Fixed: the progress window (Scan BIOS, Read, Find drive) stuck at 100% and could not be closed, "
        "not even with X. It now closes by itself when done, and X/Esc/Cancel stop the job and close it.",
        "(1.1.0) Connection help (“Help” next to “Connect”): wiring, every PD parameter and what the "
        "drive must hold, what 8N2 is (PD-01 = 0), keypad steps, the computer's ports and a checklist.",
        "(1.1.0) “Find drive”: tries every baud, format and address 1–10; if nothing answers it says why "
        "(no signal at all, adapter echo only, or baud/format mismatch).",
        "(1.1.0) The link defaults to the drives' factory setting: 9600 · 8N2 · address 1. Existing "
        "installations switch to it once.",
        "(1.1.0) The port list refreshes itself when opened.",
        "(1.0.0) First version: live monitoring, start/stop and Hz over RS-485, settings by "
        "category with search, Read/Load of all parameters, BIOS version tracking.",
    ],
}
