# -*- coding: utf-8 -*-
"""
Builds UVFD.exe and the update package.

    python build.py             dist/UVFD/UVFD.exe + paket/UVFD.zip + paket/uvfd.json
    python build.py --release   the same, then commit check, push and a GitHub
                                release vX.Y.Z with UVFD.zip + uvfd.json -
                                every running UVFD then offers the update

New version: raise VERSION and write CHANGES in uvfd/version.py first.
The self-test runs before anything is built; a failing test stops the build.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAME = "UVFD"
DIST = HERE / "dist" / NAME
PAKET = HERE / "paket"

sys.path.insert(0, str(HERE))
from uvfd.version import CHANGES, REPO, VERSION  # noqa: E402

# The Windows console is cp1251 - a "✓" there breaks printing AFTER the build
# and makes it look as if the whole build failed.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def run(cmd, **kw):
    print("›", " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, cwd=HERE, check=True, **kw)


def selftest():
    run([sys.executable, "tests/test_core.py"])


def build():
    if not (HERE / "uvfd/resources/uvfd.ico").exists():
        run([sys.executable, "tools/make_icon.py"])
    shutil.rmtree(HERE / "build", ignore_errors=True)
    shutil.rmtree(DIST, ignore_errors=True)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN", f"{NAME}.spec"])
    (DIST / "ПРОЧИТАЈ.txt").write_text(
        f"UVFD {VERSION} — контролер за фреквентен регулатор (Winston WSTG600 / SUSWE SU650)\r\n"
        "\r\n"
        "Поставување:\r\n"
        "  1. Отпакувај ја папката UVFD во C:\\UVFD (или друга папка каде корисникот\r\n"
        "     смее да запишува). НЕ во Program Files — програмата се ажурира сама.\r\n"
        "  2. Пушти UVFD.exe. Нема инсталација.\r\n"
        "\r\n"
        "Податоците (поставки, зачувани профили, BIOS верзии) се во папката data\\.\r\n"
        "Ажурирањето не ја допира.\r\n"
        "\r\n"
        "RS-485: A(D+) -> 485+, B(D-) -> 485-. Ако нема одговор, замени ги A и B.\r\n",
        encoding="utf-8-sig",
    )


def pack() -> Path:
    PAKET.mkdir(exist_ok=True)
    zip_path = PAKET / f"{NAME}.zip"
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(DIST.rglob("*")):
            if f.is_file():
                z.write(f, Path(NAME) / f.relative_to(DIST))
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    manifest = {"version": VERSION, "date": datetime.date.today().isoformat(), "sha256": digest,
                "size": zip_path.stat().st_size, "changes": CHANGES}
    (PAKET / "uvfd.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✓ {zip_path.name} {VERSION} — {zip_path.stat().st_size / 1048576:.1f} MB, sha256 {digest[:12]}…")
    return zip_path


def release(zip_path: Path):
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=HERE, capture_output=True, text=True).stdout.strip()
    if dirty:
        sys.exit("✕ Има некомитирани измени — прво commit, па --release.\n" + dirty)
    run(["git", "push", "origin", "HEAD"])
    notes = "\n".join("- " + c for c in CHANGES.get("mk", [])) + "\n\n" + \
            "\n".join("- " + c for c in CHANGES.get("en", []))
    run(["gh", "release", "create", "v" + VERSION, str(zip_path), str(PAKET / "uvfd.json"),
         "--repo", REPO, "--title", "UVFD " + VERSION, "--notes", notes])
    print(f"✓ release v{VERSION} on github.com/{REPO} — running copies will offer the update")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", action="store_true")
    ap.add_argument("--skip-tests", action="store_true")
    a = ap.parse_args()
    if not a.skip_tests:
        selftest()
    build()
    z = pack()
    if a.release:
        release(z)
