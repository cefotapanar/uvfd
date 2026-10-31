# -*- coding: utf-8 -*-
"""
Builds uvfd/resources/catalog.json - the parameter catalog for the
WSTG600 / SU650 family (Inovance MD-family register layout).

Sources, in order of trust:

  1. VFDTool drives/winston/wstg600.json - 243 entries verified against real
     drives (decimals, signed, composite, read-only, factory values);
  2. VFDTool drives/suswe/su-650.json    - 336 entries extracted from the
     SU-650 manual's own table (names, units, ranges, stop-only marks);
  3. the WSTG600 manual, chapter 6       - the long description of each
     parameter, used as the help text.

    python tools/build_catalog.py [--vfdtool DIR] [--manual PDF]

Run it again only when a source changes; the result is committed.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = ROOT / "uvfd" / "resources" / "catalog.json"

DEF_VFDTOOL = Path(r"C:\Users\cefot\Desktop\Stvari\AI\VFDTool")
DEF_MANUAL = Path(r"C:\Users\cefot\Desktop\Stvari\AI\UPATSTVA\VFD\WSTG600\WSTG600 inverter user manual.pdf")

HEXD = "0123456789ABCDEF"

GROUPS = [
    # id, mk, en
    ("P0", "Основни", "Basic"),
    ("P1", "Мотор", "Motor"),
    ("P2", "Векторска контрола", "Vector control"),
    ("P3", "V/F контрола", "V/F control"),
    ("P4", "Влезови", "Inputs"),
    ("P5", "Излези", "Outputs"),
    ("P6", "Старт / стоп", "Start / stop"),
    ("P7", "Тастатура и дисплеј", "Keypad & display"),
    ("P8", "Дополнителни функции", "Enhanced functions"),
    ("P9", "Заштити и грешки", "Protection & faults"),
    ("PA", "PID", "PID"),
    ("PB", "Нишање / должина", "Wobble / length"),
    ("PC", "Мулти-брзини и PLC", "Multi-speed & PLC"),
    ("PD", "Комуникација", "Communication"),
]

# Names VFDTool proved on hardware where the SU-650 table says otherwise.
NAME_OVERRIDE = {
    "P7-10": "Product (model) number",
    "P7-11": "Software (BIOS) version",
    "P7-08": "Inverter rated voltage",
}

UNIT_HINTS = [("(kW)", "kW"), ("(kHz)", "kHz"), ("(Hz)", "Hz"), ("(V)", "V"), ("(A)", "A"),
              ("(rpm)", "rpm"), ("(%)", "%"), ("(C)", "°C"), ("(min)", "min"), ("(h)", "h"),
              ("(kWh)", "kWh"), ("(ms)", "ms"), ("(deg)", "°")]


# --------------------------------------------------------------------------- helpers

def code_of(g: int, i: int) -> str:
    return "P%s-%02d" % (HEXD[g], i)


def clean_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def tidy_name(name: str) -> str:
    """'[read] MAXIMUM FREQUENCY' -> 'Maximum frequency'."""
    n = clean_ws(name).replace("[read] ", "")
    letters = [c for c in n if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        # Upper-cased for emphasis in VFDTool - keep acronyms short words only.
        words = []
        for w in n.split(" "):
            if len(w) <= 3 and w.isupper():
                words.append(w)
            else:
                words.append(w.capitalize())
        n = " ".join(words)
        n = n[0].upper() + n[1:]
    return n


def dec_from_text(*texts: str) -> int | None:
    """'0.000s~1.000s' -> 3. None when nothing numeric is there."""
    for t in texts:
        m = re.search(r"-?\d+\.(\d+)", t or "")
        if m:
            return len(m.group(1))
    for t in texts:
        if re.search(r"\d", t or ""):
            return 0
    return None


def parse_options(text: str) -> list[list]:
    """'0: Panel 1: Terminal 2: Comm' -> [[0,'Panel'],[1,'Terminal'],[2,'Comm']]."""
    if not text or re.search(r"units|tens|hundreds|bit\s*0|place", text, re.I):
        return []
    parts = re.split(r"(?:(?<=\s)|^)(\d{1,2})\s*[:：]\s*", " " + text)
    out, seen = [], set()
    for k in range(1, len(parts) - 1, 2):
        try:
            n = int(parts[k])
        except ValueError:
            continue
        label = clean_ws(parts[k + 1])
        if not label or n in seen:
            continue
        seen.add(n)
        out.append([n, label])
    # A real option list counts up; anything else is prose with digits in it.
    nums = [o[0] for o in out]
    if len(out) < 2 or nums != sorted(nums):
        return []
    return out


def parse_minmax(text: str, dec: int):
    """'0.00Hz~50.00Hz' -> (0, 5000) in raw units; None where not numeric."""
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*[A-Za-z%℃°/]*\s*[~～]\s*(-?\d+(?:\.\d+)?)", text or "")
    lo = hi = None
    if m:
        try:
            lo = round(float(m.group(1)) * 10 ** dec)
            hi = round(float(m.group(2)) * 10 ** dec)
        except ValueError:
            lo = hi = None
        if lo is not None and hi is not None and lo > hi:
            lo, hi = hi, lo
    return lo, hi


UNITS = ["kHz", "Hz", "kWh", "kW", "V", "A", "rpm", "%", "ms", "s", "min", "h", "°C", "m", "mH", "Ω"]


def unit_from(name: str, su_unit: str, rng: str) -> str:
    u = (su_unit or "").replace("℃", "°C").replace("degrees", "kWh").strip()
    if u in UNITS:
        return u
    for hint, unit in UNIT_HINTS:
        if hint in name:
            return unit
    m = re.match(r"\s*-?\d+(?:\.\d+)?\s*([A-Za-z%℃°Ω]+)\s*[~～]", rng or "")
    if m:
        u = m.group(1).replace("℃", "°C")
        if u in UNITS:
            return u
    return ""


# Parameters that share one option table in the manual, which prints it once
# (and the SU-650 extraction split it over several rows).
FAMILIES = [
    ["P4-%02d" % i for i in range(0, 7)],             # DI1..DI5, DI6, HDI functions
    ["P5-01", "P5-02", "P5-03", "P5-04", "P5-05"],    # FMR / relay / DO functions
    ["P5-06", "P5-07", "P5-08"],                      # FMP / AO1 / AO2 functions
]


def share_options(params: list) -> None:
    by = {p["code"]: p for p in params}
    for fam in FAMILIES:
        pool = {}
        for code in fam:
            p = by.get(code)
            if not p:
                continue
            for n, label in parse_options(p["range"]) or p["options"]:
                pool.setdefault(n, label)
            # The tail of a split table has no leading '0:' - parse it anyway.
            for m in re.finditer(r"(?:^|\s)(\d{1,2})\s*[:：]\s*(.+?)(?=\s\d{1,2}\s*[:：]|$)", p["range"]):
                pool.setdefault(int(m.group(1)), clean_ws(m.group(2)))
        if len(pool) >= 2:
            opts = [[n, pool[n]] for n in sorted(pool)]
            for code in fam:
                if code in by and "composite" not in by[code]["flags"]:
                    by[code]["options"] = opts
                    by[code]["min"] = by[code]["max"] = None
    for p in params:
        if not p["options"] and re.match(r"same as (P[0-9A-F]-\d\d)", p["range"], re.I):
            src = by.get(re.match(r"same as (P[0-9A-F]-\d\d)", p["range"], re.I).group(1).upper())
            if src:
                p["options"] = src["options"]


# --------------------------------------------------------------------------- manual help

def split_header(txt: str) -> tuple[str, str, list]:
    """
    A chapter-6 block starts with the factory value and the setting range as
    short rows ('0', 'Setting range', '0', 'Valid', '1', 'Invalid'), then the
    prose. Returns (range text, prose, options from the header rows).
    """
    lines = txt.splitlines()
    k = 0
    while k < len(lines):
        ln = lines[k]
        if len(ln) >= 45 or ln.lower().startswith("note"):
            break
        k += 1
    head, prose = lines[:k], "\n".join(lines[k:]).strip()
    rng = ""
    if any(h.lower().startswith("setting range") for h in head):
        at = next(i for i, h in enumerate(head) if h.lower().startswith("setting range"))
        rest = head[at:]
        rest[0] = rest[0][len("setting range"):].strip()
        rng = clean_ws(" ".join(r for r in rest if r))
        head = rest
    opts, seen = [], set()
    for a, b in zip(head, head[1:]):
        if re.fullmatch(r"\d{1,2}", a) and b and not re.fullmatch(r"[\d.]+", b):
            n = int(a)
            if n not in seen:
                seen.add(n)
                opts.append([n, re.sub(r"^\d{1,2}\s*[:：]\s*", "", b)])
    if len(opts) < 2 or [o[0] for o in opts] != sorted(o[0] for o in opts):
        opts = []
    return rng, prose, opts


def manual_help(pdf: Path) -> tuple[dict, dict]:
    """code -> help text, code -> name, from the WSTG600 manual's chapter 6."""
    if not pdf.exists():
        print("! manual not found, no help texts:", pdf)
        return {}, {}
    import fitz  # PyMuPDF

    doc = fitz.open(str(pdf))
    text = "\n".join(p.get_text() for p in doc)
    text = re.sub(r"\n\s*-\d{1,3}-\s*\n", "\n", text)          # page numbers
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    head = re.compile(r"\n\s*(P[0-9A-F]-\d\d)\s*\n((?:[^\n]+\n){1,3}?)\s*Factory\s+default", re.M)
    hits = list(head.finditer(text))
    helps, names = {}, {}
    for k, m in enumerate(hits):
        code = m.group(1)
        end = hits[k + 1].start() if k + 1 < len(hits) else min(len(text), m.end() + 4000)
        # Chapter 6 ends where chapter 7 (faults) starts - do not swallow it.
        block = text[m.start():end]
        cut = re.search(r"\n\s*(Chapter\s+7|7\s+Fault|Fault\s+Diagnosis)", block)
        if cut:
            block = block[:cut.start()]
        name = clean_ws(m.group(2))
        if code not in names and 2 < len(name) < 90:
            names[code] = name
        body = block[m.end() - m.start():]
        lines = [ln.strip() for ln in body.splitlines()]
        # drop the factory/range header rows (short tokens) until prose starts
        paras, cur = [], ""
        for ln in lines:
            if not ln:
                if cur:
                    paras.append(cur)
                    cur = ""
                continue
            if cur and (ln[0].islower() or cur.endswith((",", "-", "(", "and", "the", "of"))):
                cur += " " + ln
            else:
                if cur:
                    paras.append(cur)
                cur = ln
        if cur:
            paras.append(cur)
        txt = "\n".join(clean_ws(p) for p in paras if clean_ws(p))
        txt = re.sub(r"=====PAGE \d+=====", "", txt).strip()
        if code not in helps or len(txt) > len(helps[code]):
            helps[code] = txt[:3000]
    return helps, names


# --------------------------------------------------------------------------- build

def build(vfdtool: Path, manual: Path) -> dict:
    w = json.loads((vfdtool / "drives/winston/wstg600.json").read_text(encoding="utf-8"))
    s = json.loads((vfdtool / "drives/suswe/su-650.json").read_text(encoding="utf-8"))
    wc = {p["code"]: p for p in w["parameters"]}
    sc = {p["code"]: p for p in s["parameters"]}
    helps, man_names = manual_help(manual)

    params = []
    for code in sorted(set(wc) | set(sc), key=lambda c: (HEXD.index(c[1]), int(c[3:]))):
        wp, sp = wc.get(code), sc.get(code)
        g, i = HEXD.index(code[1]), int(code[3:])
        flags = set()
        for p in (wp, sp):
            for f in (p or {}).get("flags", []):
                flags.add({"model_dependent": "model", "read_only": "ro", "stop_only": "stop"}.get(f, f))
        flags.discard("name_inferred")

        su_name = sp.get("name") if sp and not sp.get("name_inferred") else None
        if su_name and su_name.lower().startswith("reserve"):
            su_name = None
        name = (NAME_OVERRIDE.get(code) or man_names.get(code) or su_name
                or (tidy_name(wp["name"]) if wp else "") or code)
        if wp and wp["name"].startswith("[read]"):
            flags.add("ro")

        h_rng, prose, h_opts = split_header(helps.get(code, ""))
        rng = clean_ws((sp or {}).get("range_text", "")) or h_rng
        if rng.lower().startswith("reserve"):
            rng = ""
        if wp:
            dec = wp["decimals"]
        else:
            d = dec_from_text((sp or {}).get("factory_text", ""), rng)
            dec = d if d is not None else (sp or {}).get("decimals", 0)

        # Factory value: the hardware-verified one first, then the manual's.
        default = wp.get("default") if wp else None
        if default is None and sp and sp.get("default") is not None and "uncertain" not in flags:
            default = sp["default"]
            if not wp and sp.get("decimals", 0) != dec and sp.get("factory_text"):
                ft = re.search(r"-?\d+(?:\.\d+)?", sp["factory_text"])
                default = round(float(ft.group(0)) * 10 ** dec) if ft else None
        if "ro" in flags:
            default = None

        options = []
        if "composite" not in flags:
            options = parse_options(rng) or h_opts or parse_options(" ".join(
                ln for ln in prose.splitlines() if re.match(r"^\d{1,2}\s*[:：]", ln)))
        if re.search(r"bit\s*0|0000\s*[-~]\s*FFFF", rng, re.I):
            flags.add("bits")
        lo, hi = (None, None) if options else parse_minmax(rng, dec)
        # Only trust a parsed range that is consistent with the register: the
        # drive itself refuses an out-of-range write (exception 3) anyway.
        rng_dec = dec_from_text(rng)
        if lo is not None and (hi > 65535 or lo < -32768 or lo >= hi
                               or (rng_dec is not None and rng_dec != dec and dec != 0)):
            lo = hi = None

        entry = {
            "code": code, "g": g, "i": i,
            "name": name,
            "dec": dec,
            "unit": unit_from(wp["name"] if wp else "", (sp or {}).get("unit", ""), rng),
            "default": default,
            "flags": sorted(flags),
            "range": rng,
            "options": options,
            "min": lo, "max": hi,
            "help": prose,
            "src": "+".join(x for x, p in (("wstg600", wp), ("su650", sp)) if p),
        }
        params.append(entry)

    share_options(params)

    groups = []
    for gid, mk, en in GROUPS:
        g = HEXD.index(gid[1])
        idx = [p["i"] for p in params if p["g"] == g]
        groups.append({"id": gid, "g": g, "mk": mk, "en": en,
                       "count": len(idx), "max_index": max(idx) if idx else 0})

    return {
        "schema": "uvfd-catalog/1",
        "family": "Winston WSTG600 / SUSWE SU650",
        "note": "Generated by tools/build_catalog.py - do not edit by hand.",
        "groups": groups,
        "params": params,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vfdtool", type=Path, default=DEF_VFDTOOL)
    ap.add_argument("--manual", type=Path, default=DEF_MANUAL)
    a = ap.parse_args()
    cat = build(a.vfdtool, a.manual)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(cat, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    ps = cat["params"]
    print("catalog: %d parameters, %d with options, %d with help, %d with factory value -> %s" % (
        len(ps), sum(1 for p in ps if p["options"]), sum(1 for p in ps if p["help"]),
        sum(1 for p in ps if p["default"] is not None), OUT))


if __name__ == "__main__":
    main()
