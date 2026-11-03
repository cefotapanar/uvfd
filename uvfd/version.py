# -*- coding: utf-8 -*-
"""
Version of UVFD.

New version: raise VERSION, write CHANGES (newest first), then
`python build.py --release`. Every running UVFD sees the new GitHub release
and offers the update.
"""

VERSION = "1.1.0"

#: GitHub repository the updater reads releases from (must be public).
REPO = "cefotapanar/uvfd"

#: Shown in the "New version" window of OLDER installations. Newest first;
#: earlier entries keep their version tag, so a jump over several versions
#: still shows everything.
CHANGES = {
    "mk": [
        "Помош за поврзување (копче „Помош“ до „Поврзи“): ожичување, сите PD параметри што се за што и што "
        "треба да стои на фреквентниот, што е 8N2 и дека е PD-01 = 0, поставување од тастатура чекор по "
        "чекор, порти на компјутерот и листа за проверка.",
        "„Пребарај фреквентен“: ги пробува сите брзини, формати и адреси 1–10. Ако не најде, кажува што е "
        "проблемот: нема никаков сигнал (жици/порта), адаптерот враќа само ехо, или брзината/форматот не се исти.",
        "Врската стандардно е фабричката на фреквентните: 9600 · 8N2 · адреса 1 (PD-00=5, PD-01=0, PD-02=1). "
        "Постоечките инсталации еднаш се префрлаат на неа.",
        "Листата на порти се освежува сама кога ќе се отвори.",
        "(1.0.0) Прва верзија: мониторинг во живо, старт/стоп и Hz преку RS-485, подесувања по "
        "категории со пребарување, Read/Load на сите параметри, следење на BIOS верзии.",
    ],
    "en": [
        "Connection help (“Help” next to “Connect”): wiring, every PD parameter and what the "
        "drive must hold, what 8N2 is (PD-01 = 0), keypad steps, the computer's ports and a checklist.",
        "“Find drive”: tries every baud, format and address 1–10; if nothing answers it says why "
        "(no signal at all, adapter echo only, or baud/format mismatch).",
        "The link defaults to the drives' factory setting: 9600 · 8N2 · address 1. Existing "
        "installations switch to it once.",
        "The port list refreshes itself when opened.",
        "(1.0.0) First version: live monitoring, start/stop and Hz over RS-485, settings by "
        "category with search, Read/Load of all parameters, BIOS version tracking.",
    ],
}
