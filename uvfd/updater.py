# -*- coding: utf-8 -*-
"""
Updates from GitHub Releases - the same flow as ULabel / Upravnik KRSTE, but
straight from GitHub, so UVFD does not depend on the ERP server.

    python build.py --release  ->  GitHub release vX.Y.Z with UVFD.zip + uvfd.json
    UVFD at start (and "Check for updates") reads releases/latest
    -> "New version X.Y.Z - Update" -> UVFD.zip into %TEMP% -> sha256 check
    -> unpack -> a helper script waits for UVFD to exit, copies the new files
       over the program folder and starts it again.

Why a helper script: Windows does not let a running .exe be overwritten.

data\\ (settings, snapshots, BIOS registry, logs) is NEVER copied over - it
belongs to that computer. The package does not carry it, and robocopy /XD
is the second lock.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .paths import FROZEN, HERE
from .version import REPO, VERSION

log = logging.getLogger("uvfd.update")

EXE_NAME = "UVFD.exe"
ZIP_NAME = "UVFD.zip"
MANIFEST_NAME = "uvfd.json"
KEEP_DIRS = ("data",)

WORK_DIR = Path(tempfile.gettempdir()) / "uvfd_update"
LOG_FILE = WORK_DIR / "update.log"
FAIL_MARK = "UPDATE_FAILED"
DONE_MARK = "UPDATE_DONE"


class UpdateError(RuntimeError):
    pass


@dataclass
class Release:
    version: str
    zip_url: str = ""
    size: int = 0
    sha256: str = ""
    date: str = ""
    notes: dict = field(default_factory=dict)      # lang -> [lines]


def _parts(version: str) -> list[int]:
    return [int(x) for x in re.findall(r"\d+", str(version or "0"))] or [0]


def is_newer(candidate: str, current: str = VERSION) -> bool:
    """'1.10.0' > '1.9.0' - by numbers, not by text."""
    a, b = _parts(candidate), _parts(current)
    n = max(len(a), len(b))
    return a + [0] * (n - len(a)) > b + [0] * (n - len(b))


def _get(url: str, timeout: float, accept: str = "application/vnd.github+json"):
    req = urllib.request.Request(url, headers={"User-Agent": "UVFD/%s" % VERSION, "Accept": accept})
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_release(repo: str = REPO) -> Release | None:
    """The latest release on GitHub, or None if there is none. Thread only."""
    try:
        with _get("https://api.github.com/repos/%s/releases/latest" % repo, 8) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    assets = {a["name"]: a for a in data.get("assets", [])}
    if ZIP_NAME not in assets:
        return None
    rel = Release(version=str(data.get("tag_name", "")).lstrip("vV"),
                  zip_url=assets[ZIP_NAME]["browser_download_url"],
                  size=int(assets[ZIP_NAME].get("size") or 0),
                  date=str(data.get("published_at", ""))[:10],
                  notes={"mk": [data.get("body") or ""], "en": [data.get("body") or ""]})
    if MANIFEST_NAME in assets:
        try:
            with _get(assets[MANIFEST_NAME]["browser_download_url"], 8, "application/octet-stream") as r:
                man = json.loads(r.read().decode("utf-8"))
            rel.sha256 = str(man.get("sha256", "")).lower()
            rel.notes = man.get("changes") or rel.notes
            rel.version = str(man.get("version") or rel.version)
        except Exception as e:                       # the zip is still usable
            log.warning("manifest: %s", e)
    return rel


def can_apply() -> tuple[bool, str]:
    if not FROZEN:
        return False, "source"
    probe = HERE / ".write_probe"
    try:
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
    except OSError:
        return False, "readonly"
    return True, ""


def download(rel: Release, on_progress=None, cancel: threading.Event | None = None) -> Path:
    """Download + verify + unpack. Returns the folder with the new version."""
    shutil.rmtree(WORK_DIR / "pkg", ignore_errors=True)
    (WORK_DIR / "pkg").mkdir(parents=True, exist_ok=True)
    target = WORK_DIR / "pkg" / ("UVFD-%s.zip" % rel.version)
    with _get(rel.zip_url, 30, "application/octet-stream") as r, open(target, "wb") as f:
        total = int(r.headers.get("Content-Length") or rel.size or 0)
        got = 0
        while True:
            if cancel is not None and cancel.is_set():
                raise UpdateError("cancelled")
            chunk = r.read(65536)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if on_progress:
                on_progress(got, total)
    if rel.sha256 and hashlib.sha256(target.read_bytes()).hexdigest() != rel.sha256:
        target.unlink(missing_ok=True)
        raise UpdateError("sha256")
    if not zipfile.is_zipfile(target):
        raise UpdateError("zip")
    out = WORK_DIR / "unpacked"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    with zipfile.ZipFile(target) as z:
        z.extractall(out)
    inner = [p for p in out.iterdir() if p.is_dir()]
    root = inner[0] if len(inner) == 1 else out
    if not (root / EXE_NAME).exists():
        raise UpdateError("no exe")
    return root


def apply(new_dir: Path) -> None:
    """Starts the helper script. The caller quits the program right after."""
    ok, why = can_apply()
    if not ok:
        raise UpdateError(why)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    script = WORK_DIR / "update.cmd"
    probe = WORK_DIR / "proc.txt"
    exe = HERE / EXE_NAME
    xd = " ".join('"%s"' % d for d in KEEP_DIRS)
    # No pipe (tasklist | find): a console-less script leaves `find` waiting
    # for input forever. The process list goes to a file. (From Upravnik.)
    script.write_text(
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "setlocal\r\n"
        'set "PID=%d"\r\n' % os.getpid()
        + 'set "LOG=%s"\r\n' % LOG_FILE
        + 'set "PROBE=%s"\r\n' % probe
        + 'echo [%DATE% %TIME%] waiting for %PID% > "%LOG%"\r\n'
        "set /a N=0\r\n"
        ":wait\r\n"
        "set /a N+=1\r\n"
        + 'if %%N%% GTR 150 (echo %s program did not exit >> "%%LOG%%" & goto start)\r\n' % FAIL_MARK
        + 'tasklist /FI "PID eq %PID%" /NH /FO CSV > "%PROBE%" 2>nul\r\n'
        'findstr /C:"\\"%PID%\\"" "%PROBE%" >nul 2>nul\r\n'
        "if not errorlevel 1 (\r\n"
        "  ping -n 2 127.0.0.1 >nul\r\n"
        "  goto wait\r\n"
        ")\r\n"
        'echo [%TIME%] copying >> "%LOG%"\r\n'
        + 'robocopy "%s" "%s" /E /IS /IT /R:3 /W:1 /NP /XD %s >> "%%LOG%%" 2>&1\r\n' % (new_dir, HERE, xd)
        + 'if errorlevel 8 (echo %s copy failed >> "%%LOG%%" & goto start)\r\n' % FAIL_MARK
        + 'echo %s >> "%%LOG%%"\r\n' % DONE_MARK
        + ":start\r\n"
        'echo [%TIME%] starting >> "%LOG%"\r\n'
        + 'start "" "%s"\r\n' % exe
        + 'del "%PROBE%" 2>nul\r\n',
        encoding="utf-8",
    )
    log.info("update: %s copies %s -> %s", script, new_dir, HERE)
    subprocess.Popen(
        ["cmd", "/c", str(script)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        close_fds=True,
    )


def last_failure() -> str | None:
    """Did the previous update fail? The log is renamed once read."""
    if not LOG_FILE.exists():
        return None
    try:
        text = LOG_FILE.read_text(encoding="utf-8", errors="replace")
        done = LOG_FILE.with_suffix(".read.log")
        done.unlink(missing_ok=True)
        LOG_FILE.rename(done)
    except OSError:
        return None
    if FAIL_MARK not in text:
        return None
    log.warning("previous update failed:\n%s", text)
    return text
