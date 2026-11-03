# -*- coding: utf-8 -*-
"""Colours, fonts and the one stylesheet. Dark industrial HMI look."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase

BG = "#0A0E13"
SURFACE = "#11171F"
SURFACE2 = "#161E28"
RAISED = "#1C2632"
HOVER = "#223042"
BORDER = "#222D3B"
BORDER_SOFT = "#1A2330"
TEXT = "#E8EEF6"
MUTED = "#9AA7B8"
FAINT = "#7A889B"
ACCENT = "#2BD4BD"          # running / ok
ACCENT_DIM = "#1A7F72"
BLUE = "#4EA1FF"            # setpoint / info
AMBER = "#F7B23B"           # warning / changed
RED = "#F2546A"             # stop / fault
RED_DIM = "#7A2633"
GREEN = "#3FDC8F"
VIOLET = "#A88BFF"          # BIOS

SERIES = [ACCENT, BLUE, AMBER, VIOLET]


def rgba(hex_: str, alpha: int) -> str:
    """CSS colour for stylesheets: rgba(r, g, b, a)."""
    c = QColor(hex_)
    return "rgba(%d,%d,%d,%d)" % (c.red(), c.green(), c.blue(), alpha)


def qc(hex_: str, alpha: int | None = None) -> QColor:
    c = QColor(hex_)
    if alpha is not None:
        c.setAlpha(alpha)
    return c


_FAMILY = "Segoe UI"
_DISPLAY = "Segoe UI"


def init_fonts() -> None:
    global _FAMILY, _DISPLAY
    fams = set(QFontDatabase.families())
    for f in ("Segoe UI Variable Text", "Segoe UI"):
        if f in fams:
            _FAMILY = f
            break
    for f in ("Segoe UI Variable Display", "Segoe UI Semibold", "Segoe UI"):
        if f in fams:
            _DISPLAY = f
            break


def font(size: float = 10, weight: int = 400, display: bool = False, tabular: bool = False) -> QFont:
    f = QFont(_DISPLAY if display else _FAMILY)
    f.setPointSizeF(size)
    f.setWeight(QFont.Weight(weight))
    if tabular:
        try:
            f.setFeature(QFont.Tag("tnum"), 1)
        except Exception:                       # older Qt - fine without
            pass
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


_ARROW = _ARROW_DIS = _CHECK = ""


def _make_arrows() -> None:
    """Combo box arrows as small PNGs - a stylesheet cannot draw a triangle."""
    global _ARROW, _ARROW_DIS, _CHECK
    import tempfile
    from pathlib import Path
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QPainter, QPen, QPixmap
    d = Path(tempfile.gettempdir()) / "uvfd_ui"
    d.mkdir(exist_ok=True)
    for name, col in (("arrow.png", MUTED), ("arrow_dis.png", FAINT)):
        pm = QPixmap(20, 20)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(col), 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline([QPointF(4, 7.5), QPointF(10, 13.5), QPointF(16, 7.5)])
        p.end()
        pm.save(str(d / name))
    pm = QPixmap(32, 32)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor("#04211D"), 4.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawPolyline([QPointF(8, 16.5), QPointF(13.5, 22), QPointF(24, 10.5)])
    p.end()
    pm.save(str(d / "check.png"))
    _CHECK = (d / "check.png").as_posix()
    _ARROW = (d / "arrow.png").as_posix()
    _ARROW_DIS = (d / "arrow_dis.png").as_posix()


def stylesheet() -> str:
    _make_arrows()
    return f"""
* {{ outline: 0; }}
QWidget {{ background: transparent; color: {TEXT}; }}
QMainWindow, QDialog, #Root {{ background: {BG}; }}
QToolTip {{ background: {RAISED}; color: {TEXT}; border: 1px solid {BORDER}; padding: 6px 8px; border-radius: 6px; }}

#TopBar {{ background: {SURFACE}; border-bottom: 1px solid {BORDER_SOFT}; }}
#Card {{ background: {SURFACE}; border: 1px solid {BORDER_SOFT}; border-radius: 14px; }}
#CardTitle {{ color: {MUTED}; font-size: 8.5pt; font-weight: 600; letter-spacing: 1px; }}
#Muted {{ color: {MUTED}; }}
#Faint {{ color: {FAINT}; }}
#Brand {{ font-size: 15pt; font-weight: 700; letter-spacing: 0.5px; }}
#BrandSub {{ color: {MUTED}; font-size: 8.5pt; }}
#Sep {{ background: {BORDER}; max-width: 1px; min-width: 1px; }}

QPushButton {{
  background: {RAISED}; border: 1px solid {BORDER}; border-radius: 9px;
  padding: 7px 14px; color: {TEXT}; font-weight: 600;
}}
QPushButton:hover {{ background: {HOVER}; border-color: #2E3D50; }}
QPushButton:pressed {{ background: {SURFACE2}; }}
QPushButton:disabled {{ color: {FAINT}; background: {SURFACE2}; border-color: {BORDER_SOFT}; }}
QPushButton[kind="primary"] {{ background: {ACCENT}; color: #04211D; border: 1px solid {ACCENT}; }}
QPushButton[kind="primary"]:hover {{ background: #46E3CE; }}
QPushButton[kind="primary"]:disabled {{ background: {SURFACE2}; color: {FAINT}; border-color: {BORDER}; }}
QPushButton[kind="ghost"] {{ background: transparent; border: 1px solid transparent; color: {MUTED}; padding: 6px 10px; }}
QPushButton[kind="ghost"]:hover {{ background: {RAISED}; color: {TEXT}; }}
QPushButton[kind="ghost"]:checked {{ background: {RAISED}; color: {TEXT}; border-color: {BORDER}; }}
QPushButton[kind="nav"] {{ background: {SURFACE2}; border: 1px solid {BORDER}; padding: 8px 12px; }}
QPushButton[kind="nav"]:hover {{ background: {HOVER}; }}
QPushButton[kind="run"] {{
  background: #0F2A27; border: 1px solid #1E5B53; color: {ACCENT}; font-size: 11pt; font-weight: 700;
  padding: 12px 10px; border-radius: 12px;
}}
QPushButton[kind="run"]:hover {{ background: #133631; border-color: {ACCENT}; }}
QPushButton[kind="run"]:disabled {{ background: {SURFACE2}; color: {FAINT}; border-color: {BORDER_SOFT}; }}
QPushButton[kind="run"][active="true"] {{ background: {ACCENT}; color: #04211D; border-color: {ACCENT}; }}
QPushButton[kind="stop"] {{
  background: {RED}; border: 1px solid {RED}; color: #2A0309; font-size: 13pt; font-weight: 800;
  padding: 14px 10px; border-radius: 12px; letter-spacing: 2px;
}}
QPushButton[kind="stop"]:hover {{ background: #FF6B80; }}
QPushButton[kind="stop"]:pressed {{ background: #D9425A; }}
QPushButton[kind="stop"]:disabled {{ background: {RED_DIM}; color: #3B1219; border-color: {RED_DIM}; }}
QPushButton[kind="small"] {{ padding: 5px 10px; font-weight: 600; font-size: 9pt; border-radius: 7px; }}
QPushButton[kind="chip"] {{
  padding: 4px 10px; border-radius: 13px; font-size: 9pt; font-weight: 600;
  background: {SURFACE2}; border: 1px solid {BORDER}; color: {MUTED};
}}
QPushButton[kind="chip"]:hover {{ color: {TEXT}; border-color: {BLUE}; }}
QPushButton[kind="lang"] {{ padding: 4px 8px; border-radius: 7px; font-size: 8.5pt; font-weight: 700;
  background: transparent; border: 1px solid transparent; color: {FAINT}; }}
QPushButton[kind="lang"]:checked {{ background: {RAISED}; color: {TEXT}; border-color: {BORDER}; }}
QPushButton[kind="danger"] {{ background: transparent; border: 1px solid {RED_DIM}; color: {RED}; padding: 5px 10px; font-size: 9pt; border-radius: 7px; }}
QPushButton[kind="danger"]:hover {{ background: #2A1218; border-color: {RED}; }}
QPushButton[kind="danger"]:disabled {{ color: {FAINT}; border-color: {BORDER_SOFT}; }}
QPushButton[kind="update"] {{ background: #2A2210; border: 1px solid #6A5418; color: {AMBER}; padding: 6px 12px; }}
QPushButton[kind="update"]:hover {{ background: #3A2E12; }}

QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{
  background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 9px;
  selection-background-color: {ACCENT_DIM}; selection-color: {TEXT}; min-height: 18px;
}}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: #2F3E52; }}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {ACCENT}; }}
QComboBox:disabled, QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{ color: {FAINT}; }}
QComboBox::drop-down {{ border: 0; width: 24px; }}
QComboBox::down-arrow {{ image: url("{_ARROW}"); width: 10px; height: 10px; margin-right: 8px; }}
QComboBox::down-arrow:disabled {{ image: url("{_ARROW_DIS}"); }}
QComboBox QAbstractItemView {{ background: {RAISED}; border: 1px solid {BORDER}; border-radius: 8px;
  padding: 4px; selection-background-color: {HOVER}; outline: 0; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: 0; }}
QLineEdit[kind="search"] {{ padding-left: 6px; border-radius: 10px; background: {SURFACE2}; font-size: 10.5pt; }}

QSlider::groove:horizontal {{ height: 6px; background: {RAISED}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {BLUE}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 18px; height: 18px; margin: -7px 0; border-radius: 9px;
  border: 3px solid {BLUE}; }}
QSlider::handle:horizontal:disabled {{ border-color: {FAINT}; background: {MUTED}; }}
QSlider::sub-page:horizontal:disabled {{ background: {FAINT}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {RAISED}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {HOVER}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {RAISED}; border-radius: 4px; min-width: 30px; }}

QTableView, QTreeView, QListView {{
  background: {SURFACE}; border: 1px solid {BORDER_SOFT}; border-radius: 12px;
  gridline-color: transparent; selection-background-color: #18324A;
  alternate-background-color: #131A23;
}}
QTableView::item, QTreeView::item {{ padding: 4px 6px; border: 0; }}
QTableView::item:selected, QTreeView::item:selected {{ background: #18324A; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: {SURFACE}; color: {MUTED}; border: 0; border-bottom: 1px solid {BORDER};
  padding: 8px 6px; font-weight: 600; font-size: 8.5pt; }}
QTableCornerButton::section {{ background: {SURFACE}; border: 0; }}

QListWidget#Nav {{ background: transparent; border: 0; padding: 0; }}
QListWidget#Nav::item {{ padding: 8px 10px; border-radius: 8px; margin: 1px 0; color: {MUTED}; }}
QListWidget#Nav::item:hover {{ background: {SURFACE2}; color: {TEXT}; }}
QListWidget#Nav::item:selected {{ background: {RAISED}; color: {TEXT}; }}

QProgressBar {{ background: {RAISED}; border: 0; border-radius: 4px; height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1px solid {BORDER}; background: {SURFACE2}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url("{_CHECK}"); }}
QCheckBox::indicator:disabled {{ background: {BG}; border-color: {BORDER_SOFT}; }}

QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 7px 14px; border: 0; border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabWidget::pane {{ border: 0; }}

QMenu {{ background: {RAISED}; border: 1px solid {BORDER}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {HOVER}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 8px; }}

QStatusBar {{ background: {SURFACE}; border-top: 1px solid {BORDER_SOFT}; color: {MUTED}; font-size: 8.5pt; padding-left: 14px; }}
QStatusBar QLabel {{ padding: 0 6px; }}
QStatusBar::item {{ border: 0; }}
QMessageBox {{ background: {SURFACE}; }}
QTextBrowser {{ background: transparent; border: 0; }}
QSplitter::handle {{ background: transparent; }}
"""
