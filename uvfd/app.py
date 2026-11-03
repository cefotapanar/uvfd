# -*- coding: utf-8 -*-
"""
Start-up: logging, the Qt application, the theme, the bus and the main window.

    UVFD.exe                     normal start
    UVFD.exe --demo [21|502]     connect to the simulated drive
    UVFD.exe --shot DIR          (development) demo run + screenshots of every window
"""

from __future__ import annotations

import argparse
import gc
import logging
import logging.handlers
import sys
import traceback

from . import i18n, paths
from .version import VERSION


def setup_logging():
    paths.ensure_dirs()
    h = logging.handlers.RotatingFileHandler(paths.LOGS / "uvfd.log", maxBytes=1_000_000, backupCount=3,
                                             encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(h)
    logging.getLogger("uvfd").info("UVFD %s start, folder %s", VERSION, paths.HERE)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="UVFD")
    ap.add_argument("--demo", nargs="?", const="21", default=None)
    ap.add_argument("--shot", default=None)
    ap.add_argument("--lang", default=None)
    args = ap.parse_args(argv)

    setup_logging()
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication, QMessageBox

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("UVFD")
    app.setApplicationVersion(VERSION)
    app.setStyle("Fusion")
    from PySide6.QtCore import QLocale
    QLocale.setDefault(QLocale.c())          # "37.50", never "37,50" - same as the drive's keypad

    from .ui import theme as th
    th.init_fonts()
    from PySide6.QtGui import QPalette
    pal = app.palette()
    for role, col in ((QPalette.Text, th.TEXT), (QPalette.WindowText, th.TEXT), (QPalette.HighlightedText, th.TEXT),
                      (QPalette.Highlight, "#18324A"), (QPalette.Base, th.SURFACE), (QPalette.Window, th.BG),
                      (QPalette.Button, th.RAISED), (QPalette.ButtonText, th.TEXT), (QPalette.ToolTipBase, th.RAISED),
                      (QPalette.ToolTipText, th.TEXT), (QPalette.PlaceholderText, th.FAINT)):
        pal.setColor(role, th.qc(col))
    app.setPalette(pal)
    app.setStyleSheet(th.stylesheet())
    app.setFont(th.font(10))

    from .bus import Bus
    from .catalog import Catalog
    from .store import FirmwareRegistry, Settings
    from .ui.common import Ctx, app_icon
    from .ui.main_window import MainWindow

    settings = Settings()
    if args.lang:
        settings["lang"] = args.lang
    i18n.set_lang(settings.get("lang", "mk"))
    app.setWindowIcon(app_icon())

    cat = Catalog.load()
    fw = FirmwareRegistry()
    fw.drop_demo_artifacts()
    try:
        import json as _json
        from .paths import resource
        fw.merge_seed(_json.loads(resource("firmware_seed.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    for v in fw.versions.values():                       # registers found by earlier scans
        for code in ((v.get("scan") or {}).get("present") or []):
            cat.ensure(code)
    bus = Bus(cat, i18n.lang)
    ctx = Ctx(cat=cat, bus=bus, settings=settings, fw=fw)

    def excepthook(t, v, tb):
        text = "".join(traceback.format_exception(t, v, tb))
        logging.getLogger("uvfd").error("unhandled:\n%s", text)
        try:
            QMessageBox.critical(None, "UVFD", str(v) + "\n\n" + str(paths.LOGS / "uvfd.log"))
        except Exception:
            pass
    sys.excepthook = excepthook

    # Upravnik/ULabel lesson: the cyclic GC running in the bus thread can
    # finalize Qt objects off the GUI thread. Collect only here, in the GUI.
    gc.disable()
    from PySide6.QtCore import QTimer
    gc_timer = QTimer()
    gc_timer.timeout.connect(lambda: gc.collect())
    gc_timer.start(5000)

    win = MainWindow(ctx, demo=args.demo or (args.shot and "502"))
    win.show()
    if args.shot:
        from .shots import Shooter
        Shooter(win, args.shot).start()
    return app.exec()
