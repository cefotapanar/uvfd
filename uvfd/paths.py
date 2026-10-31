# -*- coding: utf-8 -*-
"""
Where things live.

    <program folder>\\UVFD.exe
    <program folder>\\data\\settings.json      settings (port, language ...)
    <program folder>\\data\\snapshots\\*.json   saved parameter sets (Read / Load)
    <program folder>\\data\\firmware.json      what is known about each BIOS version
    <program folder>\\data\\logs\\              log and recordings

The updater never touches data\\ - it belongs to that computer, not to the
package. Run from source, the program folder is the repository and data\\ is
git-ignored.
"""

from __future__ import annotations

import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))

if FROZEN:
    HERE = Path(sys.executable).resolve().parent
    _RES = Path(getattr(sys, "_MEIPASS", HERE)) / "uvfd" / "resources"
else:
    HERE = Path(__file__).resolve().parent.parent
    _RES = Path(__file__).resolve().parent / "resources"

DATA = HERE / "data"
SNAPSHOTS = DATA / "snapshots"
LOGS = DATA / "logs"


def ensure_dirs() -> None:
    for d in (DATA, SNAPSHOTS, LOGS):
        d.mkdir(parents=True, exist_ok=True)


def resource(name: str) -> Path:
    return _RES / name
