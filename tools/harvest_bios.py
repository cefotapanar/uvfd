# -*- coding: utf-8 -*-
"""
Collects the BIOS versions real drives have shown to the installed UVFD and
puts them into uvfd/resources/firmware_seed.json, which ships with the next
version - so every installation knows them and none of them is "new" again.

    python tools/harvest_bios.py [--source C:\\UVFD\\data\\firmware.json ...]

build.py runs this before every build; with --release it also commits the
seed when something was added. The source file is only READ, never changed.

What goes into the seed (the repository is public):
  * the BIOS key, the model numbers, first-seen date;
  * a scan: which registers exist, and the values ONLY of registers the
    manual does not know (shown as "new · value N") - never the drive's
    ordinary settings (motor data, ramps, customer setups);
  * factory captures (they are factory values, nothing site-specific).
Not taken: DEMO connections (simulator identities), notes, user labels' notes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from uvfd.catalog import Catalog            # noqa: E402
from uvfd.sim import DEMO_IDS               # noqa: E402
from uvfd.store import norm_models          # noqa: E402

SEED = ROOT / "uvfd" / "resources" / "firmware_seed.json"
DEFAULT_SOURCES = [Path(r"C:\UVFD\data\firmware.json")]


def _clean_version(key: str, v: dict, known: set) -> dict | None:
    models = norm_models(v.get("models") or [])
    scan = v.get("scan")
    if not scan and models and all((key, m) in DEMO_IDS for m in models):
        return None                                   # a DEMO connection, not a drive
    out = {"sw": key, "models": models, "first_seen": v.get("first_seen", ""), "seen": 0,
           "scan": None, "factory": dict(v.get("factory") or {}), "note": ""}
    if scan:
        out["scan"] = {"date": scan.get("date", ""), "present": list(scan.get("present") or []),
                       "ranges": dict(scan.get("ranges") or {}),
                       "values": {c: val for c, val in (scan.get("values") or {}).items() if c not in known}}
    return out


def _basic(versions: dict) -> str:
    scanned = [(len(v["scan"]["present"]), k) for k, v in versions.items() if v.get("scan")]
    return min(scanned)[1] if scanned else ""


def harvest(sources: list[Path], seed_path: Path = SEED) -> dict:
    """Merges the sources into the seed. Returns {"added": [...], "filled": [...], "changed": bool}."""
    known = {p.code for p in Catalog.load().params}
    seed = {"schema": "uvfd-firmware-seed/1", "base": "", "versions": {}, "models": {}}
    if seed_path.exists():
        seed.update(json.loads(seed_path.read_text(encoding="utf-8")))
    added, filled = [], []
    for src in sources:
        if not src.exists():
            continue
        data = json.loads(src.read_text(encoding="utf-8"))
        for key, v in (data.get("versions") or {}).items():
            clean = _clean_version(key, v, known)
            if clean is None:
                continue
            have = seed["versions"].get(key)
            if have is None:
                seed["versions"][key] = clean
                added.append(key)
                continue
            if not have.get("scan") and clean.get("scan"):
                have["scan"] = clean["scan"]
                filled.append(key)
            if not have.get("factory") and clean.get("factory"):
                have["factory"] = clean["factory"]
                filled.append(key)
            for m in clean["models"]:
                if m not in have.setdefault("models", []):
                    have["models"].append(m)
                    filled.append(key)
        for mno, lab in (data.get("models") or {}).items():
            if mno not in seed["models"]:
                seed["models"][mno] = {k: lab[k] for k in ("model", "kw", "out_a", "supply", "series") if k in lab}
                added.append("model %s" % mno)
    base = seed.get("base") or ""
    if not base or not (seed["versions"].get(base) or {}).get("scan"):
        seed["base"] = _basic(seed["versions"])
    changed = bool(added or filled) or base != seed["base"]
    if changed:
        seed["note"] = "Built by tools/harvest_bios.py from real drives - do not edit by hand."
        seed_path.write_text(json.dumps(seed, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"added": added, "filled": sorted(set(filled)), "changed": changed, "base": seed["base"],
            "total": len(seed["versions"])}


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, action="append")
    a = ap.parse_args()
    r = harvest(a.source or DEFAULT_SOURCES)
    print("BIOS seed: %d versions, base %s; added %s; filled %s" % (
        r["total"], r["base"] or "-", ", ".join(r["added"]) or "-", ", ".join(r["filled"]) or "-"))


if __name__ == "__main__":
    main()
