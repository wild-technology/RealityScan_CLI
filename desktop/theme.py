"""Deterministic readable Windows fonts, including offscreen Qt rendering."""
import os
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication


def ensure_ui_font():
    """Qt's offscreen Windows backend can omit the system font database."""
    families = QFontDatabase.families()
    windows_dir = os.environ.get("WINDIR") or os.environ.get("SystemRoot")
    if "Segoe UI" not in families and os.name == "nt" and windows_dir:
        font = Path(windows_dir) / "Fonts" / "segoeui.ttf"
        if font.is_file():
            QFontDatabase.addApplicationFont(str(font))
    app = QApplication.instance()
    if app and "Segoe UI" in QFontDatabase.families():
        app.setFont(QFont("Segoe UI", 10))
