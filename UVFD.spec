# -*- mode: python ; coding: utf-8 -*-
# Run through build.py, not directly (build.py also makes the update package).
#
# A folder (onedir), not a single .exe: the one-file variant unpacks itself
# into %TEMP% on every start (VFDTool measured 13 s) and antivirus software
# dislikes it. The folder is replaced as a whole by the updater (robocopy).
# Same as ULabel and Upravnik KRSTE.

from PyInstaller.utils.hooks import collect_submodules

hidden = collect_submodules("uvfd") + ["serial.tools.list_ports"]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("uvfd/resources/catalog.json", "uvfd/resources"),
           ("uvfd/resources/uvfd.ico", "uvfd/resources")],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Qt modules UVFD never touches - each one is megabytes in the package.
    excludes=["tkinter", "numpy", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick",
              "PySide6.QtPdf", "PySide6.QtWebEngineCore", "PySide6.QtMultimedia", "PySide6.Qt3DCore",
              "PySide6.QtOpenGL", "PySide6.QtDBus", "PIL", "fitz", "pytest"],
    noarchive=False,
    optimize=0,
)
# Software OpenGL (20 MB) and Qt's own translations are never used by a
# widgets-only window. libssl/libcrypto stay: the updater talks HTTPS.
a.binaries = [b for b in a.binaries if not b[0].lower().endswith("opengl32sw.dll")]
a.datas = [d for d in a.datas if "/translations/" not in d[0].replace("\\", "/")]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="UVFD",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon="uvfd/resources/uvfd.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="UVFD",
)
