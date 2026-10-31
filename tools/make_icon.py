# -*- coding: utf-8 -*-
"""Writes uvfd/resources/uvfd.ico from the same drawing the window uses (ui.common.app_icon)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image                                   # noqa: E402
from PySide6.QtCore import QBuffer, QIODevice           # noqa: E402
from PySide6.QtWidgets import QApplication              # noqa: E402

from uvfd.ui.common import app_icon                     # noqa: E402

app = QApplication([])
buf = QBuffer()
buf.open(QIODevice.WriteOnly)
app_icon(256).pixmap(256, 256).toImage().save(buf, "PNG")
import io                                               # noqa: E402
img = Image.open(io.BytesIO(bytes(buf.data())))
out = ROOT / "uvfd" / "resources" / "uvfd.ico"
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icon ->", out)
