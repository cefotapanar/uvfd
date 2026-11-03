# -*- coding: utf-8 -*-
"""
Everything UVFD keeps on disk (all under data\\, never touched by updates):

  settings.json       language, port, link, safety timeout ...
  snapshots\\*.json    named parameter sets - "Read" saves one, "Load" writes it
  firmware.json       every BIOS version seen, what a scan found in it, and
                      how it differs from the base version
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import paths
from .catalog import parse_code
from .version import VERSION


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _write_json(path: Path, data) -> None:
    """Atomic: a crash halfway never leaves a broken file behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp_", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, path)


def _read_json(path: Path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


# ============================================================ settings

#: The drives' own factory link: PD-00 = 5 (9600), PD-01 = 0 (8N2), PD-02 = 1.
FACTORY_LINK = {"baud": 9600, "fmt": 0, "slave": 1}
CONN_V = 2

DEFAULTS = {
    "lang": "mk",
    "port": "",
    "baud": 9600,            # None = auto
    "fmt": 0,                # PD-01: 0=8N2 1=8E1 2=8O1 3=8N1, None = auto
    "slave": 1,
    "conn_v": CONN_V,
    "comm_timeout": 2.0,     # PD-04 while the PC runs the motor
    "poll_ms": 250,
    "pc_restore": {},        # P0-02 / P0-03 to go back to when PC control is switched off
    "preset_hz": [10.0, 25.0, 35.0, 50.0],
    "geometry": "",
    "check_updates": True,
    "skip_version": "",
}


class Settings(dict):
    def __init__(self):
        super().__init__(DEFAULTS)
        self.path = paths.DATA / "settings.json"
        data = _read_json(self.path, {})
        if isinstance(data, dict):
            self.update(data)
            # 1.1.0: the link starts at the drives' factory setting (PD-00=5 9600,
            # PD-01=0 8N2, PD-02=1) - once, also for installations from 1.0.0
            if data and data.get("conn_v", 1) < CONN_V:
                self.update(FACTORY_LINK)
                self["conn_v"] = CONN_V

    def save(self):
        _write_json(self.path, dict(self))


# ============================================================ snapshots

SNAP_SCHEMA = "uvfd-snapshot/1"


@dataclass
class SnapshotFile:
    name: str
    values: dict = field(default_factory=dict)       # code -> raw
    note: str = ""
    brand: str = ""
    date: str = ""
    app: str = ""
    drive: dict = field(default_factory=dict)       # model, sw, power, voltage
    link: str = ""
    path: Path | None = None

    @property
    def bios(self) -> str:
        sw = self.drive.get("sw", -1)
        return str(sw) if sw is not None and sw >= 0 else "?"

    def to_json(self) -> dict:
        return {"schema": SNAP_SCHEMA, "name": self.name, "note": self.note, "brand": self.brand,
                "date": self.date, "app": self.app, "drive": self.drive, "link": self.link,
                "values": dict(sorted(self.values.items(), key=lambda kv: parse_code(kv[0]) or (99, 0)))}


def slug(name: str) -> str:
    s = re.sub(r"[^\w\-. ]+", "_", name.strip(), flags=re.UNICODE).strip(" .")
    return (s or "snapshot")[:80]


def list_snapshots() -> list[SnapshotFile]:
    out = []
    if not paths.SNAPSHOTS.exists():
        return out
    for f in paths.SNAPSHOTS.glob("*.json"):
        d = _read_json(f, None)
        if not isinstance(d, dict) or d.get("schema") != SNAP_SCHEMA:
            continue
        out.append(SnapshotFile(name=d.get("name") or f.stem, values=d.get("values") or {},
                                note=d.get("note", ""), brand=d.get("brand", ""),
                                date=d.get("date", ""), app=d.get("app", ""),
                                drive=d.get("drive") or {}, link=d.get("link", ""), path=f))
    out.sort(key=lambda s: s.date, reverse=True)
    return out


def save_snapshot(s: SnapshotFile, overwrite: bool = False) -> Path:
    paths.SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    if not s.date:
        s.date = now_str()
    s.app = VERSION
    target = s.path if (overwrite and s.path) else paths.SNAPSHOTS / (slug(s.name) + ".json")
    if not overwrite:
        n = 2
        while target.exists():
            target = paths.SNAPSHOTS / ("%s (%d).json" % (slug(s.name), n))
            n += 1
    _write_json(target, s.to_json())
    s.path = target
    return target


def delete_snapshot(s: SnapshotFile) -> None:
    """Not deleted outright - moved to snapshots\\korpa, like ULabel."""
    if s.path and s.path.exists():
        bin_dir = paths.SNAPSHOTS / "korpa"
        bin_dir.mkdir(exist_ok=True)
        dest = bin_dir / s.path.name
        if dest.exists():
            dest = bin_dir / ("%s_%s.json" % (s.path.stem, datetime.now().strftime("%Y%m%d%H%M%S")))
        os.replace(s.path, dest)


def import_vfdtool(path: Path) -> list[SnapshotFile]:
    """Profiles from the old VFDTool (vfdtool_profiles.txt, [name] key=value)."""
    out, cur = [], None
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                cur = SnapshotFile(name=line[1:-1], note="VFDTool")
                out.append(cur)
                continue
            if cur is None or "=" not in line:
                continue
            k, v = (x.strip() for x in line.split("=", 1))
            gi = parse_code(k)
            try:
                iv = int(v)
            except ValueError:
                iv = None
            if gi and re.fullmatch(r"P[0-9A-F]-\d\d", k) and iv is not None:
                cur.values[k] = iv & 0xFFFF
            elif k == "date":
                cur.date = v
            elif k in ("model", "sw", "power", "voltage") and iv is not None:
                cur.drive[k] = iv
            elif k == "client" and v:
                cur.note = v
            elif k == "machine" and v:
                cur.note = (cur.note + " / " + v).strip(" /")
            elif k == "link":
                cur.link = v
    return out


# ============================================================ BIOS / firmware registry

FW_SCHEMA = "uvfd-firmware/1"


class FirmwareRegistry:
    """
    Every BIOS (software version, P7-11) seen on a drive. The BASE version is
    the reference - by default the first one ever seen, or the one the user
    marks. For every other version only the DIFFERENCES are shown: registers
    it has that the base does not, registers it lacks, and factory values
    that differ (when a factory capture exists for both).
    """

    def __init__(self, path: Path | None = None):
        self.path = path or (paths.DATA / "firmware.json")
        d = _read_json(self.path, {})
        self.base: str = d.get("base", "") if isinstance(d, dict) else ""
        self.versions: dict[str, dict] = d.get("versions", {}) if isinstance(d, dict) else {}

    def save(self):
        _write_json(self.path, {"schema": FW_SCHEMA, "base": self.base, "versions": self.versions})

    # -------------------------------------------------------------- recording
    def seen(self, key: str, model_text: str) -> bool:
        """Records a connection. Returns True when this version is NEW."""
        if key in ("?", ""):
            return False
        new = key not in self.versions
        v = self.versions.setdefault(key, {"sw": key, "models": [], "first_seen": now_str(),
                                           "seen": 0, "scan": None, "factory": {}, "note": ""})
        v["last_seen"] = now_str()
        v["seen"] = v.get("seen", 0) + 1
        if model_text and model_text not in v["models"]:
            v["models"].append(model_text)
        if not self.base:
            self.base = key
        self.save()
        return new

    def record_scan(self, key: str, found: dict, ranges: dict):
        v = self.versions.setdefault(key, {"sw": key, "models": [], "first_seen": now_str(),
                                           "seen": 0, "factory": {}, "note": ""})
        v["scan"] = {"date": now_str(), "present": sorted(found, key=lambda c: parse_code(c)),
                     "ranges": {str(g): last for g, last in ranges.items()},
                     "values": found}
        self.save()

    def record_factory(self, key: str, values: dict):
        v = self.versions.setdefault(key, {"sw": key, "models": [], "first_seen": now_str(),
                                           "seen": 0, "scan": None, "note": ""})
        v["factory"] = dict(values)
        v["factory_date"] = now_str()
        self.save()

    def set_base(self, key: str):
        if key in self.versions:
            self.base = key
            self.save()

    def scanned(self, key: str) -> bool:
        return bool((self.versions.get(key) or {}).get("scan"))

    def sorted_keys(self) -> list[str]:
        def k(s):
            try:
                return (0, int(s))
            except ValueError:
                return (1, s)
        return sorted(self.versions, key=k)

    # -------------------------------------------------------------- differences
    def reference(self, catalog_codes: set) -> tuple[set, dict, str]:
        """(present codes, factory values, label) of the base version."""
        b = self.versions.get(self.base) or {}
        scan = b.get("scan")
        present = set(scan["present"]) if scan else set(catalog_codes)
        return present, b.get("factory") or {}, self.base

    def diff(self, key: str, catalog_codes: set) -> dict:
        """
        code -> ("added" | "missing" | "factory", detail) for version `key`
        against the base. Empty for the base itself or an unscanned version.
        """
        if key == self.base or key not in self.versions:
            return {}
        v = self.versions[key]
        out = {}
        ref_present, ref_fact, _ = self.reference(catalog_codes)
        scan = v.get("scan")
        if scan:
            present = set(scan["present"])
            ranges = {int(g): last for g, last in (scan.get("ranges") or {}).items()}

            def in_range(code):
                g, i = parse_code(code)
                return g in ranges and i <= ranges[g]
            for c in present - ref_present:
                out[c] = ("added", scan["values"].get(c))
            for c in ref_present - present:
                if in_range(c):
                    out[c] = ("missing", None)
        fact = v.get("factory") or {}
        for c, val in fact.items():
            if c in ref_fact and ref_fact[c] != val and c not in out:
                out[c] = ("factory", val)
        return out

    def all_diffs(self, catalog_codes: set) -> dict[str, dict]:
        """Only versions that actually differ - one 'column' each."""
        out = {}
        for key in self.sorted_keys():
            d = self.diff(key, catalog_codes)
            if d:
                out[key] = d
        return out
