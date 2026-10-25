"""Settings, file paths, colours and small shared helpers."""
# Every module gets these through its "from .<previous> import *" line.
import copy
import ctypes
import json
import math
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import unicodedata
import uuid
import urllib.request
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
from pathlib import Path

GITHUB_REPO = "Juovitus/PokeMmoHelper"
VERSION = "v48"

# Keep data files next to the .exe when packaged, or next to the script.
if getattr(sys, "frozen", False):
    DIR = Path(sys.executable).parent
else:
    DIR = Path(__file__).resolve().parent.parent   # the folder above pmh/
TASKS_FILE = DIR / "tasks.json"
STATE_FILE = DIR / "state.json"
CONFIG_FILE = DIR / "config.json"
BERRY_FILE = DIR / "berries.json"
def _pick_sprite_dir():
    """The sprites folder next to the program, or - if that location is not
    writable (Program Files, a read-only share) - one under AppData."""
    import tempfile
    for base in (DIR, Path(os.environ.get("LOCALAPPDATA") or
                           Path.home()) / "PokeMmoHelper",
                 Path(tempfile.gettempdir()) / "PokeMmoHelper"):
        try:
            folder = base / "sprites"
            folder.mkdir(parents=True, exist_ok=True)
            probe = folder / ".w"
            probe.write_bytes(b"x")
            probe.unlink()
            return folder
        except Exception:
            continue
    return DIR / "sprites"


SPRITE_DIR = _pick_sprite_dir()

# Hour (UTC) when your checklist resets. Change this to match the game's
# daily reset - I'm not certain what it is, so verify in-game.
RESET_HOUR_UTC = 0

# How the game window is recognized (case/accent/invisible-character proof).
GAME_TITLE = "PokeMMO"
GAME_CLASS = "SDL_app"

# Default pinned spot: pixels right/down from the top-left of the game view.
PIN_OFFSET = (10, 10)

# Where the window sits when the game isn't open and it hasn't been moved.
START_POS = "+40+120"

# Checklist window size (width, height) and the smallest allowed size.
DEFAULT_SIZE = (360, 420)
MIN_SIZE = (320, 140)

# Sprites are 96px; this divides them down (2 -> 48px).
SPRITE_SHRINK = 2


BG = "#1e1f26"
BAR = "#2b2d38"
FG = "#e6e6e6"
ACCENT = "#7aa2f7"
SWITCH = "#4fd6e0"
SHADOW = "#c58bf0"   # "Keep using Shadow Ball": Gengar's whole plan
BUTTON_BORDER = "#5a6270"   # outline around buttons so they stand out
RED = "#ff4d4d"
AMBER = "#e0af68"
DIM = "#9aa0b4"
TEAM = "#c0caf5"
ORANGE = "#e8913a"   # Pokemon names
DIVIDER = "#565a6e"  # thin line between a name and its move
HOVER = "#3a3d4c"
PAGE_COLORS = {"Gym Tracker": "#7aa2f7",     # blue
               "Elite Four": "#c58bf0",      # purple
               "Berry Planter": "#7ed957"}   # green
PAGE_PALETTE = ["#7aa2f7", "#c58bf0", "#7ed957", "#f0a050", "#f2778a",
                "#4fd1c5"]                   # for pages without a set colour
CHECK_GREEN = "#3fd16b"  # the tick in a checked box
CARD = "#262833"         # berry cards
TRACK = "#14151a"        # empty part of a progress bar

IS_WIN = sys.platform == "win32"


# ---------------------------------------------------------------- helpers
def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def day_key():
    shifted = datetime.now(timezone.utc) - timedelta(hours=RESET_HOUR_UTC)
    return shifted.date().isoformat()


def write_log(name, text):
    """Append to a log file next to the program, falling back to the temp
    folder if that location isn't writable."""
    import tempfile
    for base in (DIR, Path(tempfile.gettempdir())):
        try:
            with open(base / name, "a") as f:
                f.write(text)
            return
        except Exception:
            continue


def log_error(exc_type, exc, tb):
    """Log errors (the .exe has no console window, so they'd be invisible)."""
    import traceback
    write_log("crash.log", datetime.now().isoformat() + "\n"
              + "".join(traceback.format_exception(exc_type, exc, tb)) + "\n")


def _clean(text):
    """Lowercase ASCII letters and digits only, so invisible or odd characters
    in a window title or class name can't break a match."""
    text = unicodedata.normalize("NFKD", text).lower()
    return "".join(c for c in text if c.isascii() and c.isalnum())


def page_color(page, index):
    """A page's colour: its own "color" setting, a built-in one by name, or the
    next one from the palette."""
    color = str(page.get("color") or "")
    if re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        return color
    return PAGE_COLORS.get(page.get("name"),
                           PAGE_PALETTE[index % len(PAGE_PALETTE)])
