"""Product identity and resources, also inside PyInstaller's one-file bundle."""
from pathlib import Path
import tkinter as tk

APP_NAME = "Оттиск Фото"
VERSION = "1.1.11"
ASSETS = Path(__file__).resolve().parent.parent / "assets"


def set_icon(window):
    icon = ASSETS / "logo.ico"
    if icon.is_file():
        try:
            window.iconbitmap(str(icon))
        except tk.TclError:
            pass
