"""
PokeMmoHelper - a small always-on-top checklist for PokeMMO.

It is a completely separate program. It does NOT open the game process, read
its memory, inject anything, or send input. It only asks Windows where the
window titled PokeMMO is, so it can sit next to it. You click the boxes
yourself.

- Always on top and always visible: it stays above other windows, whether or
  not PokeMMO is open, and it cannot be minimized away. "-" collapses it to
  just the title bar (it keeps its width); the button then shows "+".
- While PokeMMO is closed a "Launch PokeMMO" button shows in the title bar.
  The first click asks for PokeMMO.exe and remembers it.
- Pinned (default): sits at the top-left of the game view and follows the game
  window. It can't be dragged while pinned.
- Unpin: drag it anywhere. Pin again to lock it at its new spot relative to
  the game window. Every launch starts pinned at the top-left.
- Only one copy runs: starting a second one closes the first.
- Updates: once at start and every 6 hours it checks the latest GitHub
  release (GITHUB_REPO below). A green "Update available" button appears when
  a newer one exists; click it to download and install. The refresh button
  checks on demand.
- The title ("Gym Tracker") is a dropdown: click it to switch between pages
  such as "Gym Tracker" and "Elite Four".
- The "Elite Four" page has one dropdown per region. Open one, pick the
  champion, then the Pokemon the opponent led with, and follow the steps; pick
  the option that matches what the opponent does and the guide continues.
  Pick which of your teams the guide is written for with the "Team" selector.
- Resize with the corner grip at the bottom right (size is remembered).
  Scroll with the mouse wheel or the thin scrollbar.
- The "Berry Planter" page tracks berries you have planted in game: pick the
  berry from "Plant a berry", then each berry card shows its picture, ETA, a
  progress bar that goes red -> amber -> green as it nears harvest, a countdown
  to the next watering and a "Watered" button. White ticks on the bars mark
  when each berry needs water (a dark tick = already watered). A small berry
  bar sits next to the page title on EVERY page (the berry closest to ready),
  and a blue water drop shows when any berry needs watering.
- Each page has its own colour (title, stripe under the title bar and the
  page menu), so you can tell them apart at a glance. Set "color": "#rrggbb"
  on a page in tasks.json to change it.
- Each checklist entry is a dropdown: click its name to expand it, tick the box
  on its row to mark it complete. Ticking a gym hides its details.
- x quits.

Files created next to this program:
  tasks.json   your pages and checklists (see the Hoenn entry for the format)
  state.json   today's progress (resets daily)
  config.json  saved settings:
                 game_path        PokeMMO.exe location (set by the Launch button)
                 auto_launch      true = start the game when the tracker opens
                 pokemon_display  "both" (default), "sprites" or "names"
                 window_size      [width, height]
                 e4_team          which team the Elite Four guide follows
                 berry_overrides  fix a berry's timings, e.g.
                                  {"leppa": {"growth": 22, "first_water": 8,
                                             "water_every": 10}}  (hours)
                 e4_data_dir      optional: folder holding teams.json + teams/
  berries.json the berries you have planted (kept until you remove them)
  sprites/     Pokemon pictures: the ones packed into the exe are used first,
               anything else is downloaded once from PokeAPI and cached
  e4/          Elite Four guide data (teams.json and teams/<team>/en/*.json),
               copied from the FarmOracle "data" folder. If it is missing the
               tracker also looks in a "data" folder next to it, or in the
               folder named by e4_data_dir.

Following the game window is Windows-only; elsewhere it is a normal
free-floating window. Works over the game in windowed or borderless mode;
exclusive fullscreen will cover it.
"""
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
VERSION = "v44.1"

# Keep data files next to the .exe when packaged, or next to the script.
if getattr(sys, "frozen", False):
    DIR = Path(sys.executable).parent
else:
    DIR = Path(__file__).parent
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

# The first version of tasks.json; replaced automatically by the new default.
OLD_DEFAULT_TASKS = [
    "Kanto gyms",
    "Johto gyms",
    "Hoenn gyms",
    "Sinnoh gyms",
    "Unova gyms",
    "Elite Four",
]

# Notes that older default files contained and that were removed on request.
DROPPED_NOTES = {"Without the badge: up left x6, down right x2."}

# The Elite Four page: one dropdown per region, each holding the step-by-step
# guide ("guide" is the data file name).
E4_TASKS = [
    {"name": "Kanto", "guide": "elite4_kanto"},
    {"name": "Johto", "guide": "elite4_johto"},
    {"name": "Hoenn", "guide": "elite4_hoenn"},
    {"name": "Sinnoh", "guide": "elite4_sinnoh"},
    {"name": "Unova", "guide": "elite4_unova"},
]

# tasks.json is {"pages": [{"name": ..., "tasks": [...]}, ...]}. A task is a
# plain name or {"name": ..., "items": [...]}. An item is a name or
# {"name", "team", "note"} (all but name optional). "team" is text like
# "Garchomp Earthquake + Togekiss Hyper Voice" (first word = Pokemon, rest =
# move) or a list of {"pokemon": "Mr. Mime", "move": "..."}.
# Ticking every item ticks the task; ticking the task ticks every item.
BERRY_PAGE = {"name": "Berry Planter", "type": "berries", "tasks": []}

DEFAULT_PAGES = [
    {"name": "Gym Tracker", "tasks": [
        {"name": "Kanto gyms", "items": [
            {"name": "Vermilion City",
             "team": "Aerodactyl Rock Slide + Garchomp Earthquake"},
            {"name": "Celadon City",
             "team": "Togekiss Hyper Voice + Typhlosion Eruption",
             "note": "If Ninetales leads, swap Togekiss for Vanilluxe "
                     "Blizzard."},
            {"name": "Cinnabar Island",
             "team": "Aerodactyl Rock Slide + Blastoise Water Spout",
             "note": "If Blastoise faints, go Vanilluxe Blizzard."},
            {"name": "Pewter City",
             "team": "Garchomp Earthquake + Aerodactyl Rock Slide"},
            {"name": "Saffron City",
             "team": "Typhlosion Eruption + Aerodactyl Rock Slide",
             "note": "Aerodactyl must be full HP. If Snorlax paralyzes "
                     "Typhlosion, switch Garchomp Earthquake."},
            {"name": "Fuchsia City",
             "team": "Typhlosion Eruption + Blastoise Water Spout",
             "note": "Constant swaps will happen during the fight, don't "
                     "use Earthquake on your own Pokemon."},
            {"name": "Cerulean City",
             "team": "Blastoise Water Spout + Aerodactyl Rock Slide",
             "note": "Skippable gym. If Frillish or Quagsire, hard switch "
                     "Vanilluxe Blizzard + Typhlosion Eruption. Togekiss "
                     "as Aerodactyl replacement."},
            {"name": "Heal and head to Unova with Aerodactyl and "
                     "Typhlosion", "number": False},
        ]},
        {"name": "Johto gyms", "items": [
            {"name": "Violet City",
             "team": "Vanilluxe Blizzard + Aerodactyl Rock Slide",
             "note": "Icy Wind against Pelipper if it leads, otherwise "
                     "Blizzard. Blastoise Blizzard/Water Spout as "
                     "replacement."},
            {"name": "Ecruteak City",
             "team": "Togekiss Air Cutter + Vanilluxe Blizzard",
             "note": "If Cursed Body, swap for Blastoise Blizzard or "
                     "Typhlosion Eruption."},
            {"name": "Olivine City",
             "team": "Typhlosion Eruption + Blastoise Water Spout",
             "note": "If Mantine, swap Blastoise for Vanilluxe Blizzard "
                     "after killing Steelix."},
            {"name": "Cianwood City",
             "team": "Garchomp Earthquake + Togekiss Hyper Voice",
             "note": "If Garchomp faints, go Typhlosion Eruption."},
            {"name": "Goldenrod City",
             "team": "Vanilluxe Blizzard + Typhlosion Eruption"},
            {"name": "Azalea Town",
             "team": "Typhlosion Eruption + Togekiss Air Cutter"},
            {"name": "Mahogany Town",
             "team": "Typhlosion Eruption + Aerodactyl Rock Slide"},
            {"name": "Blackthorn City",
             "team": "Typhlosion Eruption + Togekiss Hyper Voice",
             "note": "If Pelipper or Jellicent leads, swap Typhlosion for "
                     "Vanilluxe Blizzard. Then Blastoise Blizzard."},
        ]},
        {"name": "Hoenn gyms", "items": [
            {"name": "Mossdeep City",
             "team": "Typhlosion Eruption + Blastoise Water Spout",
             "note": "Put Choice Specs on Blastoise just for this gym. "
                     "Skippable gym."},
            {"name": "Mauville City",
             "team": "Garchomp Earthquake + Aerodactyl Rock Slide",
             "note": "Togekiss Hyper Voice as Aerodactyl replacement."},
            {"name": "Lavaridge Town",
             "team": "Garchomp Earthquake + Aerodactyl Rock Slide"},
            {"name": "Rustboro City",
             "team": "Garchomp Earthquake + Aerodactyl Rock Slide"},
            {"name": "Petalburg City",
             "team": "Garchomp Earthquake + Togekiss Hyper Voice",
             "note": "If Slaking + Blissey/Stantler, swap Garchomp for "
                     "Typhlosion Eruption."},
            {"name": "Dewford Town",
             "team": "Blastoise Water Spout + Togekiss Hyper Voice"},
            {"name": "Fortree City",
             "team": "Vanilluxe Blizzard/Icy Wind + Aerodactyl Rock Slide",
             "note": "Icy Wind against Pelipper if it leads, otherwise "
                     "Blizzard."},
        ]},
        {"name": "Sinnoh gyms", "items": [
            {"name": "Eterna City",
             "team": "Typhlosion Eruption + Togekiss Hyper Voice"},
            {"name": "Hearthome City",
             "team": "Togekiss Air Cutter + Vanilluxe Blizzard",
             "note": "If Cursed Body, swap for Blastoise Blizzard / "
                     "Typhlosion Eruption."},
            {"name": "Oreburgh City",
             "team": "Aerodactyl Rock Slide/Protect + Garchomp Earthquake",
             "note": "Tyranitar + Excadrill lead: Aerodactyl Protect. "
                     "Gigalith + Excadrill: swap Garchomp for Vanilluxe "
                     "Blizzard + Aerodactyl Protect."},
            {"name": "Canalave City", "number": 1,
             "team": "Aerodactyl Rock Slide + Garchomp Earthquake",
             "note": "Gigalith + Excadrill: swap Garchomp for Vanilluxe "
                     "Blizzard + Aerodactyl Protect. Bring Garchomp back "
                     "after."},
            {"name": "Pastoria City",
             "team": "Typhlosion Eruption + Togekiss Hyper Voice",
             "note": "If Pelipper or Jellicent leads, swap Typhlosion for "
                     "Vanilluxe Blizzard. Bring Typhlosion back after."},
            {"name": "Sunyshore City",
             "team": "Typhlosion Eruption + Aerodactyl Rock Slide",
             "note": "If Pelipper, swap Typhlosion for Vanilluxe Blizzard "
                     "+ Aerodactyl Protect. Bring Typhlosion back after."},
            {"name": "Veilstone City",
             "team": "Typhlosion Eruption + Aerodactyl Rock Slide"},
            {"name": "Snowpoint City",
             "team": "Aerodactyl Rock Slide + Typhlosion Eruption"},
            {"name": "Fly to Veilstone, head south (Route 214)",
             "number": False},
            {"name": "Fly to Hearthome, head south (Route 212)",
             "number": False},
            {"name": "Fly to Sunyshore, head west (Route 222)",
             "number": False},
            {"name": "Fly to Celestic, head east (Route 210)",
             "number": False,
             "note": "Use Defog before 1st trainer. Aerodactyl Rock "
                     "Slide/Ice Fang."},
            {"name": "Fly to Twinleaf, continue north", "number": False},
        ]},
        {"name": "Unova gyms", "items": [
            {"name": "Castelia City",
             "team": "Aerodactyl Rock Slide/Protect + Typhlosion Eruption",
             "note": "Aerodactyl Protect against Durant or Flygon only if "
                     "they lead."},
            {"name": "Morimoto", "number": False,
             "team": "Garchomp Earthquake (lead)",
             "note": "Use mainly super effective moves. Keep Garchomp "
                     "alive, switch if needed."},
            {"name": "Striaton City",
             "info": "Fire: Aerodactyl Rock Slide + Blastoise Water Spout\n"
                     "Grass: Togekiss Hyper Voice + Vanilluxe Blizzard\n"
                     "Water: Typhlosion Eruption",
             "note": "Heal if low PP or HP. Garchomp Earthquake as "
                     "replacement."},
            {"name": "Nimbasa City",
             "team": "Togekiss Hyper Voice + Typhlosion Eruption"},
            {"name": "Opelucid City",
             "team": "Typhlosion Eruption + Vanilluxe Blizzard",
             "note": "Heal if low PP or HP. Blastoise Blizzard as "
                     "replacement."},
            {"name": "Nacrene City",
             "team": "Typhlosion Eruption + Aerodactyl Rock Slide",
             "note": "Garchomp Earthquake if Typhlosion faints. END OF "
                     "FIRST HOUR here."},
            {"name": "Driftveil City",
             "team": "Blastoise Water Spout + Togekiss Hyper Voice",
             "note": "If Krookodile, switch Blastoise for Vanilluxe "
                     "Blizzard."},
            {"name": "Mistralton City",
             "team": "Vanilluxe Blizzard (Icy Wind if Pelipper) + "
                     "Aerodactyl Rock Slide"},
            {"name": "Icirrus City",
             "team": "Typhlosion Eruption + Aerodactyl Rock Slide"},
            {"name": "Route 13 Rich Trainers", "number": False,
             "team": "Vanilluxe Ice Beam (for both trainers)"},
            {"name": "Shopping Mall", "number": False,
             "team": "Togekiss Hyper Voice (for both trainers)"},
        ]},
    ]},
    {"name": "Elite Four", "tasks": E4_TASKS},
    BERRY_PAGE,
]

BG = "#1e1f26"
BAR = "#2b2d38"
FG = "#e6e6e6"
ACCENT = "#7aa2f7"
SWITCH = "#4fd6e0"
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


def task_key(page_name, task):
    return f"{page_name}::{task['name']}"


def child_key(page_name, task, item):
    return f"{page_name}::{task['name']} > {item['name']}"


def normalize_tasks(raw):
    """-> [{"name", "items": [dict, ...]}, ...] (may be empty)."""
    tasks = []
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, str):
                entry = {"name": entry}
            if not isinstance(entry, dict) or not entry.get("name"):
                continue
            items = []
            for item in entry.get("items") or []:
                if isinstance(item, str):
                    item = {"name": item}
                if isinstance(item, dict) and item.get("name"):
                    items.append(item)
            task = {"name": str(entry["name"]), "items": items}
            if entry.get("guide"):
                task["guide"] = str(entry["guide"])
            tasks.append(task)
    return tasks


def normalize_pages(raw):
    """-> [{"name", "tasks": [...]}, ...] from tasks.json content."""
    pages = []
    entries = raw.get("pages") if isinstance(raw, dict) else None
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict) and entry.get("name"):
                page = {"name": str(entry["name"]),
                        "type": str(entry.get("type") or "tasks"),
                        "tasks": normalize_tasks(entry.get("tasks"))}
                if entry.get("color"):
                    page["color"] = str(entry["color"])
                pages.append(page)
    return pages


def convert_legacy(raw):
    """Old tasks.json (one flat list) -> the pages format. "Elite Four" moves
    to its own page; removed fields and notes are dropped."""
    gyms, elite = [], []
    for entry in copy.deepcopy(raw):
        name = entry if isinstance(entry, str) else (
            entry.get("name") if isinstance(entry, dict) else None)
        if isinstance(entry, dict):
            for item in entry.get("items") or []:
                if isinstance(item, dict):
                    item.pop("route", None)
                    item.pop("puzzle", None)
                    if item.get("note") in DROPPED_NOTES:
                        item.pop("note", None)
        if str(name or "").strip().lower() == "elite four":
            elite.append(entry)
        elif name:
            gyms.append(entry)
    pages = [{"name": "Gym Tracker", "tasks": gyms}]
    if elite:
        pages.append({"name": "Elite Four", "tasks": elite})
    return pages


def write_tasks_file(pages_raw):
    try:
        TASKS_FILE.write_text(
            json.dumps({"pages": pages_raw}, indent=2, ensure_ascii=False),
            encoding="utf-8")
    except Exception:
        pass


def upgrade_pages(pages_raw):
    """Replace the old lone "Elite Four" checkbox with the region guides.
    Returns True if anything changed."""
    changed = False
    for page in pages_raw.get("pages", []):
        if not isinstance(page, dict) or page.get("name") != "Elite Four":
            continue
        tasks = page.get("tasks") or []
        plain = [t if isinstance(t, str) else t.get("name") for t in tasks
                 if isinstance(t, str) or (isinstance(t, dict)
                                           and not t.get("items")
                                           and not t.get("guide"))]
        if len(tasks) == 1 and plain == ["Elite Four"]:
            page["tasks"] = copy.deepcopy(E4_TASKS)
            changed = True
    return changed


def seed_gyms(pages_raw, config):
    """Fill region gym lists that are still empty from the built-in data.
    Done once per region (so deleting or editing one later sticks)."""
    seeded = set(config.get("seeded_gyms") or [])
    defaults = next(p for p in DEFAULT_PAGES
                    if p["name"] == "Gym Tracker")["tasks"]
    changed = False
    for page in pages_raw.get("pages", []):
        if not isinstance(page, dict) or page.get("name") != "Gym Tracker":
            continue
        tasks = page.setdefault("tasks", [])
        for default in defaults:
            if not default.get("items") or default["name"] in seeded:
                continue
            seeded.add(default["name"])
            for index, task in enumerate(tasks):
                name = task if isinstance(task, str) else task.get("name")
                if name == default["name"]:
                    if isinstance(task, str) or not task.get("items"):
                        tasks[index] = copy.deepcopy(default)
                        changed = True
                    break
    config["seeded_gyms"] = sorted(seeded)
    return changed


def load_tasks():
    """Load tasks.json -> pages. Creates it on first run and converts an
    older single-list file (keeping a copy as tasks.backup.json)."""
    pages_raw = None
    if not TASKS_FILE.exists():
        write_tasks_file(DEFAULT_PAGES)
        pages_raw = {"pages": DEFAULT_PAGES}
    else:
        raw = load_json(TASKS_FILE, None)
        if raw == OLD_DEFAULT_TASKS:
            write_tasks_file(DEFAULT_PAGES)
            pages_raw = {"pages": DEFAULT_PAGES}
        elif isinstance(raw, list):
            backup = DIR / "tasks.backup.json"
            if not backup.exists():
                try:
                    shutil.copyfile(TASKS_FILE, backup)
                except Exception:
                    pass
            converted = convert_legacy(raw)
            write_tasks_file(converted)
            pages_raw = {"pages": converted}
        else:
            pages_raw = raw
    if isinstance(pages_raw, dict):
        pages_raw = copy.deepcopy(pages_raw)
        changed = upgrade_pages(pages_raw)
        # Add the Berry Planter page to an existing file once (so deleting it
        # later sticks).
        config = load_json(CONFIG_FILE, {})
        if not config.get("berry_page_added"):
            has_berries = any(isinstance(pg, dict)
                              and pg.get("type") == "berries"
                              for pg in pages_raw.get("pages", []))
            if not has_berries:
                pages_raw.setdefault("pages", []).append(
                    copy.deepcopy(BERRY_PAGE))
                changed = True
            config["berry_page_added"] = True
        before = list(config.get("seeded_gyms") or [])
        if seed_gyms(pages_raw, config):
            changed = True
        if config.get("seeded_gyms") != before or changed:
            try:
                CONFIG_FILE.write_text(json.dumps(config, indent=2))
            except Exception:
                pass
        if changed:
            write_tasks_file(pages_raw["pages"])
    pages = normalize_pages(pages_raw)
    return pages or normalize_pages({"pages": DEFAULT_PAGES})


def migrate_done(pages, done):
    """Progress saved before pages existed used plain names as keys; carry it
    over to the page-qualified keys."""
    out = {k for k in done if "::" in k}
    for page in pages:
        for task in page["tasks"]:
            if task["name"] in done:
                out.add(task_key(page["name"], task))
            for item in task["items"]:
                if f"{task['name']} > {item['name']}" in done:
                    out.add(child_key(page["name"], task, item))
    return out


def parse_team(team):
    """-> [(pokemon, move), ...] from "Garchomp Earthquake + Togekiss Hyper
    Voice" or a list of strings / {"pokemon", "move"} dicts."""
    if isinstance(team, str):
        parts = [p.strip() for p in team.split("+") if p.strip()]
    elif isinstance(team, list):
        parts = team
    else:
        parts = []
    members = []
    for part in parts:
        if isinstance(part, dict):
            name = str(part.get("pokemon") or part.get("name") or "").strip()
            move = str(part.get("move") or "").strip()
        else:
            tokens = str(part).split(None, 1)
            name = tokens[0] if tokens else ""
            move = tokens[1] if len(tokens) > 1 else ""
        if name:
            members.append((name, move))
    return members


# PokeAPI spellings that differ from the names used in the guide.
SLUG_FIX = {"darmanitan": "darmanitan-standard",
            "meloetta": "meloetta-aria", "mrmime": "mr-mime", "hooh": "ho-oh", "irontreads": "iron-treads",
            "fanrotom": "rotom-fan", "rotomfan": "rotom-fan",
            "heatrotom": "rotom-heat", "rotomheat": "rotom-heat",
            "washrotom": "rotom-wash", "rotomwash": "rotom-wash",
            "frostrotom": "rotom-frost", "rotomfrost": "rotom-frost",
            "mowrotom": "rotom-mow", "rotommow": "rotom-mow"}


class Sprites:
    """Pokemon and item pictures. Each is downloaded once from PokeAPI (in a
    background thread, so the window never freezes) and cached in the sprites
    folder. If a download fails, the name is shown instead."""

    def __init__(self):
        self.images = {}       # (kind, slug, shrink) -> PhotoImage
        self.failed = set()    # (kind, slug)
        self.fetching = set()
        self.waiting = {}      # (kind, slug) -> [(shrink, callback), ...]
        self.done = queue.Queue()
        self.failed_at = {}    # (kind, slug) -> time of the last failure
        self.gate = threading.Semaphore(4)   # at most 4 downloads at once

    @staticmethod
    def slug(name):
        s = name.strip().lower().replace(" ", "-")
        s = re.sub(r"[^a-z0-9-]", "", s)
        return SLUG_FIX.get(s.replace("-", ""), s)

    @staticmethod
    def path(kind, slug):
        name = f"{slug}.png" if kind == "pokemon" else f"item-{slug}.png"
        local = SPRITE_DIR / name
        bundled = getattr(sys, "_MEIPASS", None)   # packed inside the exe
        if bundled and not local.exists():
            packed = Path(bundled) / "sprites" / name
            if packed.exists():
                return packed
        return local

    def _load(self, kind, slug, shrink):
        key = (kind, slug, shrink)
        if key not in self.images:
            image = tk.PhotoImage(file=str(self.path(kind, slug)))
            if shrink > 1:
                image = image.subsample(shrink)
            self.images[key] = image
        return self.images[key]

    def get(self, name, callback, shrink=None, kind="pokemon"):
        """Return the picture if available now; otherwise start fetching it
        and call callback(image) later (from the main thread)."""
        shrink = SPRITE_SHRINK if shrink is None else shrink
        slug = self.slug(name)
        if not slug:
            return None
        if (kind, slug) in self.failed:
            # a failed download is retried after a minute (network hiccup)
            if time.time() - self.failed_at.get((kind, slug), 0) < 60:
                return None
            self.failed.discard((kind, slug))
        key = (kind, slug, shrink)
        if key in self.images:
            return self.images[key]
        if self.path(kind, slug).exists():
            try:
                return self._load(kind, slug, shrink)
            except Exception:
                self.failed.add((kind, slug))
                return None
        self.waiting.setdefault((kind, slug), []).append((shrink, callback))
        if (kind, slug) not in self.fetching:
            self.fetching.add((kind, slug))
            threading.Thread(target=self._fetch, args=(kind, slug),
                             daemon=True).start()
        return None

    def _fetch(self, kind, slug):
        with self.gate:
            self._fetch_one(kind, slug)

    def _fetch_one(self, kind, slug):
        headers = {"User-Agent": "Mozilla/5.0 PokeMmoHelper"}
        for attempt in range(3):
            try:
                self._download(kind, slug, headers)
                self.done.put((kind, slug, True))
                return
            except Exception as exc:
                last = exc
                time.sleep(1.5 * (attempt + 1))
        write_log("run.log", f"sprite {kind}/{slug} failed: {last!r}\n")
        self.done.put((kind, slug, False))

    def _get_json(self, url, headers):
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.load(resp)

    @staticmethod
    def _sprite_url(data, kind):
        sprites = data.get("sprites") or {}
        if kind != "pokemon":
            return sprites.get("default")
        art = ((sprites.get("other") or {}).get("official-artwork") or {})
        return (sprites.get("front_default") or sprites.get("front_female")
                or art.get("front_default"))

    def _download(self, kind, slug, headers):
        api = "pokemon" if kind == "pokemon" else "item"
        base = "https://pokeapi.co/api/v2/"
        names = [slug]
        if kind == "pokemon":
            names += [slug + "-male", slug + "-standard", slug + "-normal"]
        url, last = None, None
        for name in names:
            try:
                url = self._sprite_url(
                    self._get_json(f"{base}{api}/{name}", headers), kind)
                if url:
                    break
            except Exception as exc:
                last = exc
        if not url and kind == "pokemon":
            # Ask the species for its default form (covers gendered and
            # alternate-form Pokemon whose plain name isn't a form).
            try:
                species = self._get_json(f"{base}pokemon-species/{slug}",
                                         headers)
                for var in species.get("varieties") or []:
                    if var.get("is_default"):
                        url = self._sprite_url(self._get_json(
                            var["pokemon"]["url"], headers), kind)
                        break
            except Exception as exc:
                last = exc
        if not url:
            raise last or ValueError("no sprite")
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            png = resp.read()
        SPRITE_DIR.mkdir(parents=True, exist_ok=True)
        self.path(kind, slug).write_bytes(png)

    def poll(self):
        """Call regularly from the main thread to deliver finished downloads."""
        while True:
            try:
                kind, slug, ok = self.done.get_nowait()
            except queue.Empty:
                return
            self.fetching.discard((kind, slug))
            callbacks = self.waiting.pop((kind, slug), [])
            if not ok:
                self.failed.add((kind, slug))
                self.failed_at[(kind, slug)] = time.time()
                continue
            for shrink, callback in callbacks:
                try:
                    callback(self._load(kind, slug, shrink))
                except Exception:
                    pass  # the widget was replaced meanwhile


# ------------------------------------------------- names found in the guide
POKEMON_NAMES = (
    "abomasnow absol accelgor aerodactyl aggron alakazam alomomola altaria "
    "amoonguss ampharos arbok arcanine archeops ariados articuno banette "
    "bastiodon beartic beautifly beedrill bisharp blastoise blaziken "
    "blissey blitzle bouffalant braviary breloom bronzong bulbasaur "
    "butterfree cacturne camerupt carracosta chandelure chansey charizard "
    "charmander chikorita chimchar cinccino claydol clefable cloyster "
    "cofagrigus conkeldurr corsola crawdaunt crobat crustle cyndaquil "
    "darmanitan dewgong ditto donphan dragonite drapion drifblim druddigon "
    "dugtrio durant dusknoir dustox eelektross eevee ekans electivire "
    "electrode emboar emolga empoleon entei escavalier espeon excadrill "
    "exeggutor fanrotom feraligatr ferrothorn flareon floatzel flygon "
    "forretress froslass frostrotom furret gallade galvantula garchomp "
    "gardevoir gastrodon gengar gigalith girafarig glaceon glalie gliscor "
    "golduck golem golurk gothitelle granbull grumpig gyarados hariyama "
    "haxorus heatran heatrotom heracross hippowdon hitmonchan hitmonlee "
    "hitmontop honchkrow hooh houndoom huntail hydreigon hypno infernape "
    "irontreads jellicent jirachi jolteon jynx kabutops kangaskhan kecleon "
    "kingdra kingler krookodile lanturn lapras latias latios leafeon "
    "leavanny lickilicky lickitung liepard lopunny lucario ludicolo luxray "
    "machamp magcargo magikarp magmortar magnezone mamoswine mandibuzz "
    "manectric mantine maractus marowak masquerain mawile medicham meganium "
    "meloetta metagross mew mewtwo mienshao mightyena milotic miltank "
    "minccino mismagius moltres mowrotom mrmime mudkip muk musharna "
    "nidoking nidoqueen ninetales noctowl octillery omastar oshawott "
    "parasect pelipper persian pidgeot pikachu piplup politoed poliwrath "
    "primeape probopass purugly quagsire raichu rapidash rayquaza regice "
    "regirock registeel relicanth reuniclus rhyperior roserade rotom "
    "rotomfan rotomfrost rotomheat rotommow rotomwash sableye salamence "
    "samurott sandslash sawk sceptile scizor scolipede scrafty scyther "
    "seaking seismitoad serperior seviper sharpedo shiftry shuckle sigilyph "
    "simipour simisage simisear skarmory skuntank slowbro slowking snivy "
    "snorlax spiritomb squirtle stantler staraptor starmie steelix "
    "stoutland stunfisk sudowoodo swalot swampert swanna swellow swoobat "
    "tangrowth tauros tentacruel tepig throh togekiss torchic torkoal "
    "torterra totodile toxicroak treecko tropius turtwig typhlosion "
    "tyranitar umbreon unfezant ursaring vanillish vanilluxe vaporeon "
    "venomoth venusaur vespiquen victreebel vileplume volcarona wailord "
    "walrein washrotom weavile weezing whimsicott whiscash wobbuffet xatu "
    "yanmega zapdos zebstrika zoroark"
).split()
DISPLAY_FIX = {"mrmime": "Mr. Mime", "hooh": "Ho-Oh",
               "irontreads": "Iron Treads"}
ROTOM_FORMS = {"Rotom Heat": "rotom-heat", "Rotom Wash": "rotom-wash",
               "Rotom Frost": "rotom-frost", "Rotom Fan": "rotom-fan",
               "Rotom Mow": "rotom-mow"}
ITEMS = {"Max Potion": "max-potion", "Full Restore": "full-restore",
         "Full Heal": "full-heal", "Hyper Potion": "hyper-potion",
         "Super Potion": "super-potion", "Max Revive": "max-revive",
         "Revive": "revive", "Potion": "potion",
         "Choice Scarf": "choice-scarf", "Choice Band": "choice-band",
         "Choice Specs": "choice-specs", "Life Orb": "life-orb",
         "Rocky Helmet": "rocky-helmet", "Leftovers": "leftovers",
         "Focus Sash": "focus-sash", "Sash": "focus-sash",
         "Sitrus Berry": "sitrus-berry", "Lum Berry": "lum-berry",
         "Oran Berry": "oran-berry", "Fighting Gem": "fighting-gem"}


def _build_mention_table():
    table = {}   # text as written -> (kind, name for the picture)
    for slug in POKEMON_NAMES:
        table[DISPLAY_FIX.get(slug, slug.capitalize())] = ("pokemon", slug)
    for text, slug in ROTOM_FORMS.items():
        table[text] = ("pokemon", slug)
    for text, slug in ITEMS.items():
        table[text] = ("item", slug)
    names = sorted(table, key=len, reverse=True)
    pattern = re.compile(
        r"(?<![A-Za-z])(" + "|".join(re.escape(n) for n in names)
        + r")(?![a-z])")
    return table, pattern


MENTIONS, MENTION_RE = _build_mention_table()


def find_mentions(text):
    """The Pokemon and items named in a line, in order, without repeats:
    [(kind, name), ...]."""
    found = []
    for match in MENTION_RE.finditer(str(text or "")):
        entry = MENTIONS[match.group(1)]
        if entry not in found:
            found.append(entry)
    return found


def clean_step(text, prev="", auto_encore=True, nxt=""):
    """Tidy guide text: one kind of bracket, no doubled brackets or spaces,
    consistent wording ("Sp.Atk", "(No Encore)"), and Encore shown first
    wherever Gengar is told to boost."""
    text = unicodedata.normalize("NFKC", str(text or ""))
    for _ in range(4):
        text = re.sub(r"\(\s*\(", "(", text)
        text = re.sub(r"\)\s*\)", ")", text)
    text = re.sub(r"\(\s*\)", "", text)
    # wording
    text = re.sub(r"\(?\s*no need to use encore( to set up)?\s*\)?",
                  "(No Encore)", text, flags=re.I)
    text = re.sub(r"\bSp\.?\s*Atk\b|\bSpecial Attack\b", "Sp.Atk", text,
                  flags=re.I)
    text = re.sub(r"\bSp\.?\s*Def\b|\bSpecial Defen[sc]e\b", "Sp.Def", text,
                  flags=re.I)
    text = re.sub(r"\bhp\b", "HP", text)
    text = re.sub(r"\bDragonite Dance(?![A-Za-z])|\bddance\b", "Dragon Dance", text,
                  flags=re.I)
    text = re.sub(r"(Dance)(?=\d)", r"\1 ", text)
    text = re.sub(r"\+\s+(?=\d)", "+", text)
    text = re.sub(r"\(\s*([^()]*?)\s*\)",
                  lambda m: "(" + re.sub(r"\s+needed\b", "", m.group(1),
                                         flags=re.I) + ")", text)
    text = re.sub(r"\(([a-z])", lambda m: "(" + m.group(1).upper(), text)
    text = re.sub(r"\bStay(?:s|ed)?\b(?: in| on the field)?"
                  r"(?: \((?:Don't|Do not|Doesn't|No) switch\))?",
                  "Didn't Switch", text, flags=re.I)
    text = re.sub(r"^[Tt]o (?=[A-Z])", "Switch to ", text)
    # the opponent's Pokemon coming in: "Enemy sends out X"
    text = re.sub(r"^→\s*(.+?)\s+(?:comes|came) (?:out|in)\b\s*",
                  r"Enemy sends out \1 ", text).rstrip()
    text = re.sub(r"^→\s*sends out\s*$", "Enemy sends out a new Pokémon",
                  text)
    text = re.sub(r"^→\s*sends out\b\s*", "Enemy sends out ", text)
    # several team numbers means it isn't known yet
    text = re.sub(r"\bOpponent is using team(?= \d+\s*,)",
                  "Opponent could be using team", text)
    # Gengar boosts: say Encore first (unless it is already covered, or the
    # next step says no Encore is needed)
    def encore_first(text):
        # "Switch to Gengar +4" -> "Switch to Gengar, Encore, then +4"
        if re.search(r"\bto Gengar \+\d", text):
            return re.sub(r"\bto Gengar (?=\+\d)", "to Gengar, Encore, then ",
                          text, 1)
        # a line that starts with the boost: "Encore, then +4 Sp.Atk"
        # (the Gengar picture shows who); mid-sentence keeps the name
        if re.match(r"Gengar \+\d", text):
            return re.sub(r"^Gengar (?=\+\d)", "Encore, then ", text, 1)
        return re.sub(r"Gengar(?= \+\d)", "Encore, then Gengar", text, 1)

    if auto_encore and re.search(r"Gengar \+\d", text) and not re.search(
            r"encore", text + " " + prev, re.I) and not re.search(
            r"no Encore", nxt, re.I):
        text = encore_first(text)
    elif auto_encore and re.search(r"Gengar \+\d", text) and re.search(
            r"\s*\+?\s*use Encore\b", text, re.I):
        # "Gengar +4 Sp.Atk + use Encore": Encore, boost, then Encore again
        text = re.sub(r"\s*\+?\s*use Encore\b", "", text, flags=re.I)
        if not re.search(r"encore", prev, re.I):
            text = encore_first(text)
        text += ", then Encore again"
    # spacing / punctuation
    text = re.sub(r"\s+([,.;:!?)%])", r"\1", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r",(?=[A-Za-z])", ", ", text)
    text = re.sub(r"\s*/\s*", " / ", text)
    text = re.sub(r"(?<=[A-Za-z0-9)])\(", " (", text)
    text = re.sub(r"\)(?=[A-Za-z0-9\u00b7\u2192])", ") ", text)
    text = re.sub(r"(\s*·\s*){2,}", " · ", text)
    text = re.sub(r"^[\s·]+|[\s·]+$", "", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    if text.startswith("vs "):
        return text
    return re.sub(r"^[a-z]", lambda m: m.group(0).upper(), text)


CONNECTOR_RE = re.compile(
    r"(switch to|to|see|use|push to|push|vs|sacrifice|then|if|let|"
    r"force the switch to|take the hit at|after|before|go to|send out)",
    re.I)


def tidy_steps(steps):
    """The guide splits some sentences into pieces ("Switch to" / "Gengar",
    "use Stealth Rock" / "+" / "Chansey ..."). Put them back together.
    -> [(kind, raw text), ...]"""
    items = [(s.get("kind"), str(s.get("text") or "")) for s in steps]
    out, i = [], 0
    while i < len(items):
        kind, text = items[i]
        plain = clean_step(text)
        nxt = items[i + 1] if i + 1 < len(items) else None
        if (nxt and kind == nxt[0] and kind != "setup"
                and plain == "+" and out and out[-1][0] == kind
                and i + 1 < len(items)):
            out[-1] = (kind, out[-1][1] + " + " + nxt[1])
            i += 2
            continue
        if (nxt and kind == nxt[0] and kind != "setup"
                and CONNECTOR_RE.fullmatch(plain)):
            out.append((kind, text + " " + nxt[1]))
            i += 2
            continue
        out.append((kind, text))
        i += 1
    return out


SWITCH_RE = re.compile(
    r"(switch to|teleport to|send in|sacrifice|double switch|encore sacrifice|let it switch)",
    re.I)


def trainer_slug(name):
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


# ------------------------------------------------------------ berry planter
# (growth hours, first watering within, then water every, berries). Source:
# the PikaMMO Berry Guide / Berry Timer; adjust any berry with the
# "berry_overrides" setting in config.json if the in-game timers differ.
BERRY_GROUPS = [
    (16, 7, 12, "cheri chesto pecha rawst aspear oran persim nanab bluk razz "
                 "pinap wepear"),
    (20, 7, 12, "leppa figy wiki mago aguav iapapa cornn magost rabuta nomel "
                 "belue"),
    (42, 8, 15, "occa passho wacan rindo yache chople kebia shuca coba payapa "
                 "tanga charti kasib haban colbur babiri chilan spelon pamtre "
                 "watmel durin enigma"),
    (44, 8, 15, "pomeg kelpsy qualot hondew grepa tamato lum sitrus micle "
                 "custap jaboca rowap"),
    (67, 8, 15, "liechi ganlon salac petaya apicot lansat starf"),
]
BERRY_HOURS = (16, 20, 42, 44, 67)


def _build_berries():
    table = {}
    for growth, first, every, names in BERRY_GROUPS:
        for slug in names.split():
            table[slug] = {"name": slug.capitalize(), "growth": growth,
                           "first_water": first, "water_every": every}
    return table


BERRIES = _build_berries()


def berry_info(slug, config=None):
    """Timings (hours) for a berry, with any config.json overrides applied."""
    info = dict(BERRIES.get(slug) or {"name": slug.capitalize(),
                                      "growth": 24, "first_water": 8,
                                      "water_every": 12})
    over = ((config or {}).get("berry_overrides") or {}).get(slug)
    if isinstance(over, dict):
        for key in ("growth", "first_water", "water_every"):
            try:
                if key in over:
                    info[key] = float(over[key])
            except (TypeError, ValueError):
                pass
    return info


def plant_status(plant, info, now):
    """Where a planted berry stands at time `now` (epoch seconds)."""
    growth = max(60.0, info["growth"] * 3600.0)
    planted = float(plant["planted"])
    ready_at = planted + growth
    waters = sorted(float(w) for w in plant.get("waters") or [])
    state = "ready" if now >= ready_at else "growing"
    water_in = None
    if state == "growing":
        if waters:
            due = waters[-1] + info["water_every"] * 3600.0
        else:
            due = planted + info["first_water"] * 3600.0
        if due < ready_at:       # otherwise no more watering is needed
            water_in = due - now
    return {"state": state,
            "progress": max(0.0, min(1.0, (now - planted) / growth)),
            "ready_in": max(0.0, ready_at - now), "ready_at": ready_at,
            "water_in": water_in, "waters": len(waters)}


def water_notches(plant, info, now):
    """Marks along a berry's progress bar: [(fraction, watered), ...].

    Watered marks are where you actually watered; the others are when it needs
    water next (counting from the last watering) and every interval after
    that, until the berry is ready."""
    growth = max(60.0, info["growth"] * 3600.0)
    every = max(60.0, info["water_every"] * 3600.0)
    planted = float(plant["planted"])
    ready_at = planted + growth
    waters = sorted(float(w) for w in plant.get("waters") or [])
    marks = [(max(0.0, min(1.0, (w - planted) / growth)), True)
             for w in waters if planted <= w < ready_at]
    if now >= ready_at:
        return marks
    due = (waters[-1] + every if waters
           else planted + info["first_water"] * 3600.0)
    while due < ready_at and len(marks) < 60:
        marks.append((max(0.0, (due - planted) / growth), False))
        due += every
    return marks


def fmt_duration(seconds):
    s = int(max(0, seconds))
    days, rem = divmod(s, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def fmt_clock(epoch):
    text = datetime.fromtimestamp(epoch).strftime("%a %I:%M %p")
    return text.replace(" 0", " ", 1)


def _rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def progress_color(fraction):
    """Red at the start, amber halfway, green when done."""
    stops = [(0.0, "#e5534b"), (0.5, "#e0af68"), (1.0, "#4cd964")]
    fraction = max(0.0, min(1.0, fraction))
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        if fraction <= p1:
            t = (fraction - p0) / (p1 - p0)
            a, b = _rgb(c0), _rgb(c1)
            return "#%02x%02x%02x" % tuple(
                round(a[i] + (b[i] - a[i]) * t) for i in range(3))
    return stops[-1][1]


def load_berry_plants():
    raw = load_json(BERRY_FILE, {})
    plants = []
    for entry in (raw.get("plants") if isinstance(raw, dict) else None) or []:
        try:
            plants.append({
                "id": str(entry.get("id") or uuid.uuid4().hex[:8]),
                "berry": str(entry["berry"]).lower(),
                "planted": float(entry["planted"]),
                "waters": [float(w) for w in entry.get("waters") or []]})
        except Exception:
            continue
    return plants


def pin_image(color, angle, bg=BAR, size=16):
    """A pushpin icon drawn pixel by pixel (no image files needed), tilted by
    `angle` degrees and blended onto `bg` so its edges look smooth."""
    def rgb(hex_color):
        return [int(hex_color[i:i + 2], 16) for i in (1, 3, 5)]

    def inside(x, y):
        # Pin pointing down, centred on (0, 0), in pixels.
        return ((-4 <= x <= 4 and -7 <= y <= -5)          # cap
                or (-2.5 <= x <= 2.5 and -5 <= y <= 0)    # body
                or (-5 <= x <= 5 and 0 <= y <= 1.5)       # collar
                or (-0.7 <= x <= 0.7 and 1.5 <= y <= 7.5))  # needle

    fg_rgb, bg_rgb = rgb(color), rgb(bg)
    cos_a = math.cos(math.radians(angle))
    sin_a = math.sin(math.radians(angle))
    samples = [(i + 0.5) / 3 for i in range(3)]
    image = tk.PhotoImage(width=size, height=size)
    rows = []
    for py in range(size):
        row = []
        for px in range(size):
            hits = 0
            for sy in samples:
                for sx in samples:
                    dx, dy = px + sx - size / 2, py + sy - size / 2
                    hits += inside(dx * cos_a + dy * sin_a,
                                   -dx * sin_a + dy * cos_a)
            mix = hits / 9
            row.append("#%02x%02x%02x" % tuple(
                round(b + (f - b) * mix) for f, b in zip(fg_rgb, bg_rgb)))
        rows.append("{" + " ".join(row) + "}")
    image.put(" ".join(rows))
    return image


def flat_button(parent, text, command, bg, fg, hover_bg, hover_fg=None,
                **options):
    """A Label that works like a flat button. Native Windows buttons flash
    white for a moment when created, which shows every time the guide is
    rebuilt; a Label is drawn by Tk in its own colours straight away."""
    hover_fg = hover_fg or fg
    label = tk.Label(parent, text=text, bg=bg, fg=fg, bd=0, cursor="hand2",
                     **options)

    def enter(_event):
        label.config(bg=hover_bg, fg=hover_fg)

    def leave(_event):
        label.config(bg=bg, fg=fg)

    def release(event):
        # like a real button: only fires if released over it
        if (0 <= event.x < label.winfo_width()
                and 0 <= event.y < label.winfo_height()):
            command()

    label.bind("<Enter>", enter)
    label.bind("<Leave>", leave)
    label.bind("<ButtonRelease-1>", release)
    return label


def canvas_size(canvas, default_w, default_h):
    try:
        width, height = int(canvas.winfo_width()), int(canvas.winfo_height())
    except Exception:
        return default_w, default_h
    return (width if width > 1 else default_w,
            height if height > 1 else default_h)


def draw_bar(canvas, fraction, color, text="", default_w=100, default_h=12,
             notches=()):
    """Paint a progress bar: a filled rectangle, watering ticks along the top
    and bottom edges (white = needs water, dark = already watered) and
    centred text with a dark outline so it stays readable on any colour."""
    width, height = canvas_size(canvas, default_w, default_h)
    canvas.delete("all")
    fraction = max(0.0, min(1.0, fraction))
    if fraction > 0:
        canvas.create_rectangle(0, 0, max(1, round(width * fraction)),
                                height, fill=color, width=0)
    tick = max(3, height // 4)      # ticks stay clear of the text
    for mark, watered in notches:
        x = min(max(round(width * mark), 1), width - 1)
        line = BG if watered else "#ffffff"
        canvas.create_line(x, 0, x, tick, width=2, fill=line)
        canvas.create_line(x, height - tick, x, height, width=2, fill=line)
    if text:
        cx, cy = width // 2, height // 2
        font = ("Segoe UI", 7, "bold")
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1),
                       (-1, -1), (1, 1), (-1, 1), (1, -1)):
            canvas.create_text(cx + dx, cy + dy, text=text, fill="#101114",
                               font=font)
        canvas.create_text(cx, cy, text=text, fill="#ffffff", font=font)


class BerryView:
    """The Berry Planter page: plant a berry, then watch each plant's card."""

    def __init__(self, app, parent):
        self.app = app
        self.frame = tk.Frame(parent, bg=BG)
        self.frame.pack(fill="x")
        self.picker_open = False
        self.hours = BERRY_HOURS[0]
        self.cards = {}
        self.confirm = {}

        top = tk.Frame(self.frame, bg=BG)
        top.pack(fill="x", pady=(0, 4))
        self.plant_button = tk.Button(
            top, command=self.toggle_picker, bg=BAR, fg=ACCENT, bd=0,
            activebackground=HOVER, activeforeground=ACCENT, padx=8, pady=2,
            font=("Segoe UI", 9, "bold"), cursor="hand2")
        self.plant_button.pack(side="left")
        self.picker = tk.Frame(self.frame, bg=BG)       # packed when open
        self.chips = tk.Frame(self.picker, bg=BG)
        self.chips.pack(fill="x")
        self.results = tk.Frame(self.picker, bg=BG)
        self.results.pack(fill="x", pady=(2, 4))
        self.list_frame = tk.Frame(self.frame, bg=BG)
        self.list_frame.pack(fill="x")
        self.update_plant_button()
        self.build_chips()
        self.rebuild()

    # -- planting picker
    def update_plant_button(self):
        self.plant_button.config(
            text="Plant a berry  " + ("▴" if self.picker_open
                                      else "▾"))

    def toggle_picker(self):
        self.picker_open = not self.picker_open
        if self.picker_open:
            self.picker.pack(fill="x", after=self.plant_button.master)
            self.render_results()
        else:
            self.picker.pack_forget()
        self.update_plant_button()

    def build_chips(self):
        for child in self.chips.winfo_children():
            child.destroy()
        for hours in BERRY_HOURS:
            active = hours == self.hours
            tk.Button(self.chips, text=f"{hours}h",
                      command=lambda h=hours: self.set_hours(h),
                      bg=ACCENT if active else BAR,
                      fg=BG if active else FG, bd=0,
                      activebackground=HOVER, font=("Segoe UI", 8, "bold"),
                      padx=8, pady=1, cursor="hand2"
                      ).pack(side="left", padx=(0, 3))

    def set_hours(self, hours):
        self.hours = hours
        self.build_chips()
        self.render_results()

    def render_results(self):
        for child in self.results.winfo_children():
            child.destroy()
        slugs = sorted(s for s, b in BERRIES.items()
                       if b["growth"] == self.hours)
        cols = 4
        for index, slug in enumerate(slugs):
            image = self.app.berry_image(slug, small=True)
            button = tk.Button(
                self.results, text=BERRIES[slug]["name"], compound="top",
                image=image if image is not None else "",
                command=lambda s=slug: self.pick(s), bg=BAR, fg=FG, bd=0,
                activebackground=HOVER, activeforeground=FG,
                font=("Segoe UI", 7), padx=2, pady=2, cursor="hand2")
            button.grid(row=index // cols, column=index % cols, padx=2,
                        pady=2, sticky="nsew")
        for col in range(cols):
            self.results.columnconfigure(col, weight=1, uniform="berry")

    def pick(self, slug):
        self.picker_open = False
        self.picker.pack_forget()
        self.update_plant_button()
        self.app.plant_berry(slug)

    # -- the planted berries
    def rebuild(self):
        """Redraw the cards (only when a berry is added or removed)."""
        for child in self.list_frame.winfo_children():
            child.destroy()
        self.cards = {}
        self.confirm = {}
        plants = self.app.berry_plants
        if not plants:
            tk.Label(self.list_frame, bg=BG, fg=DIM, anchor="w",
                     justify="left", wraplength=self.app.current_wrap(),
                     font=("Segoe UI", 8, "italic"),
                     text="No berries yet. After planting one in game, "
                          "choose it above to start its timers."
                     ).pack(fill="x")
            return
        tk.Label(self.list_frame, bg=BG, fg=DIM, anchor="w", justify="left",
                 font=("Segoe UI", 7),
                 text="White ticks on the bar edges = when it needs water  \u00b7  "
                      "dark tick = watered").pack(fill="x", pady=(0, 2))
        now = time.time()
        order = sorted(plants, key=lambda pl: plant_status(
            pl, berry_info(pl["berry"], self.app.config), now)["ready_at"])
        for plant in order:
            self.build_card(plant)
        self.update()

    def build_card(self, plant):
        pid = plant["id"]
        info = berry_info(plant["berry"], self.app.config)
        card = tk.Frame(self.list_frame, bg=CARD, padx=8, pady=6)
        card.pack(fill="x", pady=3)
        top = tk.Frame(card, bg=CARD)
        top.pack(fill="x")
        image = self.app.berry_image(plant["berry"])
        pic = tk.Label(top, bg=CARD, image=image if image is not None else "")
        pic.pack(side="left")
        mid = tk.Frame(top, bg=CARD)
        mid.pack(side="left", fill="x", expand=True, padx=8)
        tk.Label(mid, text=f"{info['name']} berry", bg=CARD, fg=FG,
                 anchor="w", font=("Segoe UI", 10, "bold")).pack(fill="x")
        eta = tk.Label(mid, bg=CARD, fg=DIM, anchor="w",
                       font=("Segoe UI", 8))
        eta.pack(fill="x")
        remove = tk.Label(top, text="✕", bg=CARD, fg=DIM,
                          cursor="hand2", font=("Segoe UI", 9, "bold"))
        remove.pack(side="right", anchor="n")
        remove.bind("<Button-1>", lambda e, i=pid: self.remove_click(i))
        bar = tk.Canvas(card, height=18, bg=TRACK, highlightthickness=0,
                        bd=0)
        bar.pack(fill="x", pady=(6, 4))
        bar.bind("<Configure>", lambda e, i=pid: self.update_one(i, True))
        bottom = tk.Frame(card, bg=CARD)
        bottom.pack(fill="x")
        water = tk.Label(bottom, bg=CARD, fg=ACCENT, anchor="w",
                         font=("Segoe UI", 9))
        water.pack(side="left")
        action = tk.Button(bottom, command=lambda i=pid: self.act(i), bd=0,
                           font=("Segoe UI", 9, "bold"), padx=10, pady=1,
                           cursor="hand2")
        self.cards[pid] = {"eta": eta, "bar": bar, "water": water,
                           "action": action, "remove": remove, "last": None,
                           "button_shown": False, "bar_state": None}

    def update(self):
        for pid in list(self.cards):
            self.update_one(pid)

    def update_one(self, pid, force=False):
        card = self.cards.get(pid)
        plant = self.app.find_plant(pid)
        if card is None or plant is None:
            return
        info = berry_info(plant["berry"], self.app.config)
        st = plant_status(plant, info, time.time())
        if st["state"] == "ready":
            eta = ("Ready to harvest!", CHECK_GREEN)
            water = ("", DIM)
            button = ("Harvested", CHECK_GREEN)
        else:
            eta = (f"Ready in {fmt_duration(st['ready_in'])}   ·   "
                   f"ETA {fmt_clock(st['ready_at'])}", DIM)
            w = st["water_in"]
            if w is None:
                water, button = ("No more watering needed", DIM), None
            else:
                if w <= 0:
                    water = (f"Needs water now!  ({fmt_duration(-w)} late)",
                             RED)
                elif w < 3600:
                    water = (f"Water in {fmt_duration(w)}", AMBER)
                else:
                    water = (f"Water in {fmt_duration(w)}", ACCENT)
                button = ("Watered", ACCENT)
        pct = int(st["progress"] * 100)
        color = progress_color(st["progress"])
        notches = tuple(water_notches(plant, info, time.time()))
        signature = (eta, water, button, pct, color, notches)
        if signature == card["last"] and not force:
            return
        card["last"] = signature
        card["eta"].config(text=eta[0], fg=eta[1])
        card["water"].config(text=water[0], fg=water[1])
        if button is None:
            if card["button_shown"]:
                card["action"].pack_forget()
                card["button_shown"] = False
        else:
            card["action"].config(text=button[0], bg=BAR, fg=button[1],
                                  activebackground=HOVER,
                                  activeforeground=button[1])
            if not card["button_shown"]:
                card["action"].pack(side="right")
                card["button_shown"] = True
        draw_bar(card["bar"], st["progress"], color,
                 "Ready" if st["state"] == "ready" else f"{pct}%",
                 default_w=280, default_h=18, notches=notches)

    def act(self, pid):
        """Watered (while growing) or Harvested (once ready)."""
        plant = self.app.find_plant(pid)
        if plant is None:
            return
        info = berry_info(plant["berry"], self.app.config)
        if plant_status(plant, info, time.time())["state"] == "ready":
            self.app.remove_plant(pid)
        else:
            self.app.water_plant(pid)

    def remove_click(self, pid):
        """First click asks for confirmation, a second click removes."""
        card = self.cards.get(pid)
        if card is None:
            return
        if self.confirm.get(pid):
            self.app.remove_plant(pid)
            return
        self.confirm[pid] = True
        card["remove"].config(text="remove?", fg=RED)

        def reset():
            self.confirm.pop(pid, None)
            try:
                card["remove"].config(text="✕", fg=DIM)
            except Exception:
                pass
        self.app.root.after(3000, reset)


# ----------------------------------------------------------- window lookup
def list_big_windows(min_w=500, min_h=350):
    """Visible, non-minimized windows of at least min_w x min_h, as
    (title, class_name, (left, top, right, bottom), hwnd) where the rectangle
    is the window's drawable area on screen (below the title bar). Only
    titles, class names and geometry are read - nothing from other programs'
    memory."""
    if not IS_WIN:
        return []
    user32 = ctypes.windll.user32
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR,
                                      ctypes.c_int]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR,
                                     ctypes.c_int]
    user32.GetWindowRect.argtypes = [wintypes.HWND,
                                     ctypes.POINTER(wintypes.RECT)]
    user32.GetClientRect.argtypes = [wintypes.HWND,
                                     ctypes.POINTER(wintypes.RECT)]
    user32.ClientToScreen.argtypes = [wintypes.HWND,
                                      ctypes.POINTER(wintypes.POINT)]
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _):
        try:
            if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
                wr = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(wr))
                if (wr.right - wr.left >= min_w
                        and wr.bottom - wr.top >= min_h):
                    title = ""
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length:
                        tbuf = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, tbuf, length + 1)
                        title = tbuf.value
                    cbuf = ctypes.create_unicode_buffer(256)
                    user32.GetClassNameW(hwnd, cbuf, 256)
                    left, top, right, bottom = (wr.left, wr.top, wr.right,
                                                wr.bottom)
                    # Prefer the client area so we pin inside the game view,
                    # not to the title bar or invisible resize borders.
                    pt = wintypes.POINT(0, 0)
                    cr = wintypes.RECT()
                    if (user32.ClientToScreen(hwnd, ctypes.byref(pt))
                            and user32.GetClientRect(hwnd, ctypes.byref(cr))
                            and cr.right > 0 and cr.bottom > 0):
                        left, top = pt.x, pt.y
                        right, bottom = pt.x + cr.right, pt.y + cr.bottom
                    out.append((title, cbuf.value,
                                (left, top, right, bottom), hwnd))
        except Exception:
            pass
        return True

    user32.EnumWindows(callback, 0)
    return out


def match_tier(title, cls):
    """How well a window matches the game: 0 best, 2 weakest, None no match.
      0: title is PokeMMO (ignoring odd/invisible characters)
      1: title contains PokeMMO and the class is the game's class
      2: class is the game's class (fallback if the title can't be matched)"""
    t, c = _clean(title), _clean(cls)
    if t == _clean(GAME_TITLE):
        return 0
    if c == _clean(GAME_CLASS):
        return 1 if _clean(GAME_TITLE) in t else 2
    return None


def find_game_window():
    """Return (rect, title, hwnd) for the game window, or None. Best match
    tier wins; among equals, the largest window. Browser tabs that merely
    mention the game never match (wrong title and wrong class)."""
    best_key, chosen = None, None
    for title, cls, rect, hwnd in list_big_windows(300, 200):
        tier = match_tier(title, cls)
        if tier is None:
            continue
        key = (tier, -(rect[2] - rect[0]) * (rect[3] - rect[1]))
        if best_key is None or key < best_key:
            best_key, chosen = key, (rect, title, hwnd)
    return chosen


# --------------------------------------------------------- Elite Four guide
_E4_CACHE = {}


def find_e4_root(config):
    """Folder holding teams.json and teams/<team>/en/elite4_*.json."""
    candidates = []
    if config.get("e4_data_dir"):
        candidates.append(Path(str(config["e4_data_dir"])))
    candidates += [DIR / "e4", DIR / "data"]
    candidates += [DIR / "e4" / "e4", DIR / "e4" / "data", DIR / "data" / "e4"]
    try:   # any folder next to the tracker that holds teams.json
        candidates += [p for p in sorted(DIR.iterdir()) if p.is_dir()]
    except Exception:
        pass
    bundled = getattr(sys, "_MEIPASS", None)   # data packed inside the exe
    if bundled:
        candidates.append(Path(bundled) / "e4")
    for folder in candidates:
        try:
            if (folder / "teams.json").is_file() and (folder / "teams").is_dir():
                return folder
        except Exception:
            continue
    return None


def load_e4_teams(root):
    """-> (teams, default_id); teams = [{"id", "name", "pokemon": [...]}]."""
    key = ("teams", str(root))
    if key not in _E4_CACHE:
        raw = load_json(root / "teams.json", {})
        teams = [t for t in raw.get("teams", [])
                 if isinstance(t, dict) and t.get("id")]
        default = raw.get("default")
        if default not in [t["id"] for t in teams] and teams:
            default = teams[0]["id"]
        _E4_CACHE[key] = (teams, default)
    return _E4_CACHE[key]


def load_e4_guide(root, team_id, guide_id):
    """Parsed guide file, or None if it is missing/unreadable."""
    key = (str(root), team_id, guide_id)
    if key not in _E4_CACHE:
        data = None
        for sub in ("en", ""):
            path = root / "teams" / team_id / sub / f"{guide_id}.json"
            if path.is_file():
                data = load_json(path, None)
                if isinstance(data, dict) and isinstance(data.get("nodes"),
                                                         dict):
                    break
                data = None
        _E4_CACHE[key] = data
    return _E4_CACHE[key]


E4_TRAINER_ALIASES = {"Gary": "Blue"}


def load_e4_opponents(root, guide_id, trainer):
    """The trainer's numbered teams from e4/opponents.json:
    [{"team": n, "pokemon": [{"pokemon", "ability", "item", "moves"}]}]."""
    key = ("opponents", str(root))
    if key not in _E4_CACHE:
        raw = load_json(root / "opponents.json", {})
        _E4_CACHE[key] = raw.get("regions", {}) if isinstance(raw, dict) else {}
    region = guide_id.split("_", 1)[-1].title()
    trainers = _E4_CACHE[key].get(region) or {}
    for name in (trainer, f"{trainer} ({region})",
                 E4_TRAINER_ALIASES.get(trainer)):
        if name and isinstance(trainers.get(name), list):
            return trainers[name]
    return []


TEAM_LINE_RE = re.compile(r"^Opponent (?:is|could be) using team", re.I)
SEND_OUT_RE = re.compile(r"^→|\b(?:comes out|comes in|sends out)\b",
                         re.I)


def team_lines_first(steps):
    """Move each "Opponent is using team N" line up to just under the step
    where the opponent sent something out (or to the top of the section, the
    heading being what was sent out), so it is read before the moves."""
    out = []
    for kind, text in steps:
        if not TEAM_LINE_RE.match(text):
            out.append((kind, text))
            continue
        spot = 0
        for index, (_kind, earlier) in enumerate(out):
            if SEND_OUT_RE.search(earlier):
                spot = index + 1
        out.insert(spot, (kind, text))
    return out


def is_pokemon_label(label):
    """True for a choice that is just the opponent's Pokemon ("Lucario",
    "Mandibuzz / Spiritomb")."""
    parts = [p for p in re.split(r"\s*/\s*", str(label).strip()) if p]
    if not parts:
        return False
    for part in parts:
        m = MENTION_RE.fullmatch(part)
        if not m or MENTIONS[m.group(1)][0] != "pokemon":
            return False
    return True


def current_label(group, nodes, trail, node_id, saved_label):
    """The button text that leads to node_id, from the guide as it is now
    (saved progress keeps the old text, which goes stale when a label is
    corrected)."""
    if not trail:
        options = group.get("entries", [])
    else:
        branch = resolve_node(nodes, trail[-1][1])[1] or {}
        options = branch.get("options", [])
    for option in options:
        if option.get("nodeId") == node_id and option.get("label"):
            return option["label"]
    return str(saved_label)


def possible_teams(texts):
    """Team numbers from the last "Opponent is using team 1, 4" line."""
    found = None
    for text in texts:
        m = re.search(r"using team ([\d,\s]+)", text)
        if m:
            found = {int(n) for n in re.findall(r"\d+", m.group(1))}
    return found


def resolve_node(nodes, node_id):
    """Follow automatic 'goto' links. Returns (steps, choice_branch|None)."""
    steps, seen, branch = [], set(), None
    while node_id in nodes and node_id not in seen:
        seen.add(node_id)
        node = nodes[node_id]
        steps.extend(node.get("steps") or [])
        branch = node.get("branch")
        if branch and branch.get("kind") == "goto":
            node_id, branch = branch.get("nodeId"), None
            continue
        break
    if branch and branch.get("kind") != "choice":
        branch = None
    return steps, branch


class GuideView:
    """One region's Elite Four guide: champion -> opponent's lead -> steps,
    choosing an option wherever the guide branches."""

    def __init__(self, app, parent, guide_id):
        self.app = app
        self.guide_id = guide_id
        self.frame = tk.Frame(parent, bg=BG)
        self.frame.pack(fill="x")
        self.group = None      # chosen champion (a dict from the guide)
        self.trail = []        # [(label, node_id), ...] choices made so far
        self.menu_open = False
        self.teams_open = False  # the trainer's team list (accordion)
        self.root = None         # folder with the Elite Four data
        self.rendered = False
        saved = (app.ui_guides or {}).get(guide_id)
        self.pending = saved if isinstance(saved, dict) else None

    # -- state changes (each re-renders after the click finishes)
    def state(self):
        return {"group": self.group["name"] if self.group else None,
                "trail": [[label, node] for label, node in self.trail]}

    def later(self):
        self.app.ui_changed()
        self.app.save_ui_now()
        self.app.root.after_idle(self.render)

    def ensure_rendered(self):
        if not self.rendered:
            self.render()

    def refresh(self):
        """The team changed: start this guide over."""
        self.group, self.trail, self.menu_open = None, [], False
        self.pending = None
        self.app.ui_changed()
        if self.rendered:
            self.render()

    def toggle_menu(self):
        self.menu_open = not self.menu_open
        self.later()

    def pick_team(self, team_id):
        self.menu_open = False
        self.app.set_e4_team(team_id)

    def pick_group(self, group):
        self.group, self.trail = group, []
        self.later()

    def pick_step(self, label, node_id):
        self.trail.append((label, node_id))
        self.later()

    def back(self):
        if self.trail:
            self.trail.pop()
            # steps that were followed automatically go too, or Back would
            # just follow them again
            while self.trail and self.only_option(self.trail[-1][1]):
                self.trail.pop()
        else:
            self.group = None
        self.later()

    def only_option(self, node_id):
        """The single option of a choice that has just one, else None."""
        branch = resolve_node(getattr(self, "nodes", {}), node_id)[1] or {}
        options = branch.get("options", [])
        return options[0] if len(options) == 1 else None

    def follow_only_options(self):
        """A "choice" with one possible answer isn't a choice: take it."""
        seen = {node_id for _label, node_id in self.trail}
        while self.trail:
            option = self.only_option(self.trail[-1][1])
            if option is None or option["nodeId"] in seen:
                break
            self.trail.append((option["label"], option["nodeId"]))
            seen.add(option["nodeId"])

    def restart(self):
        self.group, self.trail = None, []
        self.later()

    # -- drawing
    def text(self, parent, text, fg, font, pady=0):
        text = clean_step(text)
        label = tk.Label(parent, text=text, bg=BG, fg=fg, font=font,
                         justify="left", anchor="w",
                         wraplength=self.app.current_wrap())
        label.pack(fill="x", pady=pady)
        self.app.wrap_labels.append(label)
        return label

    def button(self, parent, text, command, fg=FG, wrap=0):
        return flat_button(parent, text, command, BAR, fg, HOVER,
                           font=("Segoe UI", 8), padx=6, pady=2,
                           wraplength=wrap, justify="left")

    def rich(self, text, fg, font, pady=0):
        """A line of text with the pictures of the Pokemon and items it
        names shown beside it. Steps arrive already cleaned (with the step
        before them in mind), so don't add "Encore, then" a second time."""
        text = clean_step(text, auto_encore=False)
        marks = find_mentions(text)[:4]
        if (not marks and getattr(self, "has_gengar", False)
                and re.match(r"\W*Encore\b", text)):
            marks = [("pokemon", "gengar")]   # Gengar is the one with Encore
        if not marks:
            return self.text(self.frame, text, fg, font, pady)
        row = tk.Frame(self.frame, bg=BG)
        row.pack(fill="x", pady=pady)
        strip = tk.Frame(row, bg=BG)
        strip.pack(side="left", anchor="n", padx=(0, 3))
        for kind, name in marks:
            pic = tk.Label(strip, bg=BG)
            pic.pack(side="left")
            self.picture(pic, kind, name, 3 if kind == "pokemon" else 1)
        label = tk.Label(row, text=text, bg=BG, fg=fg, font=font,
                         justify="left", anchor="w")
        label.pack(side="left", fill="x", expand=True)
        offset = 34 * len(marks)
        self.app.wrap_labels.append(label)
        self.app.wrap_off[label] = offset
        label.config(wraplength=max(60, self.app.current_wrap() - offset))
        return label

    def picture(self, widget, kind, name, shrink, compound="left"):
        """Put a Pokemon / item / trainer picture on a label or button, now
        or when its download finishes."""
        def show(image, widget=widget):
            if image is not None:
                widget.config(image=image, compound=compound)

        if kind == "trainer":
            show(self.app.trainer_image(name, small=shrink >= 3))
            return
        image = self.app.sprites.get(name, show, shrink=shrink, kind=kind)
        if image is not None:
            show(image)

    def grid(self, choices, cols, trainers=False):
        grid = tk.Frame(self.frame, bg=BG)
        grid.pack(fill="x", pady=(2, 2))
        buttons = []

        def fit(_event=None):
            """Wrap every button's text to the width its column really has
            (minus the sprite beside it), so text wraps and the button
            grows taller instead of being cut off. Computed from the grid's
            own width, so it can't feed back on itself."""
            try:
                total = grid.winfo_width()
                if total < 50:
                    return
                col_w = total / cols - 4          # cell padding
                for b in buttons:
                    img = str(b.cget("image"))
                    pic = 0
                    if img and str(b.cget("compound")) == "left":
                        pic = int(b.tk.call("image", "width", img)) + 6
                    room = max(30, int(col_w - 2 - 12 - 4 - pic))
                    if getattr(b, "_room", None) != room:
                        b._room = room
                        b.config(wraplength=room)
            except Exception:
                pass

        def refit(_event=None):
            if getattr(grid, "_refit", None) is None:
                grid._refit = grid.after_idle(
                    lambda: (setattr(grid, "_refit", None), fit()))

        for index, (text, command) in enumerate(choices):
            # A 1px frame around each button gives it a visible outline
            # (a Button's own highlight ring doesn't show on every system).
            cell = tk.Frame(grid, bg=BUTTON_BORDER)
            # starts narrow so the columns can share the width evenly;
            # fit() sets the real wrap width as soon as the grid is laid out
            button = self.button(cell, clean_step(text, auto_encore=False),
                                 command, wrap=40)
            button.bind("<Configure>", refit)   # picture arrived, etc.
            button.pack(fill="both", expand=True, padx=1, pady=1)
            cell.grid(row=index // cols, column=index % cols, padx=2,
                      pady=2, sticky="nsew")
            buttons.append(button)
            if trainers:
                self.picture(button, "trainer", text, 2, compound="top")
            else:
                marks = find_mentions(text)
                if marks:
                    self.picture(button, marks[0][0], marks[0][1], 3)
        for col in range(cols):
            grid.columnconfigure(col, weight=1, uniform="choice")
        # every row as tall as the tallest, so all choices match in height
        for row in range((len(choices) + cols - 1) // cols):
            grid.rowconfigure(row, weight=1, uniform="choice_row")
        grid.bind("<Configure>", fit)
        refit()

    def render(self):
        # Rebuilding changes the page height, which can move the view; keep
        # it where it was (applied when the new layout is measured, before
        # it is drawn, so nothing flashes).
        if self.rendered:
            self.app.hold_scroll(self.app.canvas.canvasy(0))
            self.app.freeze_body()
        try:
            self.build()
        finally:
            # after the layout work queued by build() has run
            self.app.root.after_idle(self.app.thaw_body)

    def build(self):
        self.rendered = True
        for child in self.frame.winfo_children():
            child.destroy()
        self.app.prune_wrap()
        root = self.root = find_e4_root(self.app.config)
        if root is None:
            self.text(self.frame,
                      "Elite Four guide data not found. Rebuild the exe with "
                      "the 'e4' folder next to build_exe.bat (it gets packed "
                      "inside), or put 'e4' next to the exe, or set "
                      "\"e4_data_dir\" in config.json.\nLooked in: "
                      f"{DIR}  (tracker {VERSION})", AMBER,
                      ("Segoe UI", 8))
            return
        teams, default = load_e4_teams(root)
        if not teams:
            self.text(self.frame, "No teams found in teams.json.", AMBER,
                      ("Segoe UI", 8))
            return
        team_id = self.app.e4_team(teams, default)
        team = next(t for t in teams if t["id"] == team_id)
        self.has_gengar = "Gengar" in team.get("pokemon", [])
        self.team_header(teams, team)
        data = load_e4_guide(root, team_id, self.guide_id)
        if data is None:
            self.text(self.frame,
                      f"No guide for {team['name']} in this region.", AMBER,
                      ("Segoe UI", 8))
            return
        if self.pending:
            saved, self.pending = self.pending, None
            group = next((g for g in data.get("groups", [])
                          if g.get("name") == saved.get("group")), None)
            if group is not None:
                self.group = group
                nodes = data.get("nodes", {})
                trail = []
                for pair in saved.get("trail") or []:
                    if (isinstance(pair, list) and len(pair) == 2
                            and pair[1] in nodes):
                        trail.append((current_label(group, nodes, trail,
                                                    pair[1], pair[0]),
                                      pair[1]))
                    else:
                        break
                self.trail = trail
        if self.group is None:
            self.render_champions(data)
        elif not self.trail:
            self.render_leads()
        else:
            self.render_steps(data)

    def team_header(self, teams, team):
        row = tk.Frame(self.frame, bg=BG)
        row.pack(fill="x")
        tk.Label(row, text="Team:", bg=BG, fg=DIM,
                 font=("Segoe UI", 8)).pack(side="left")
        name = tk.Label(row, text=f"{team['name']}  ▾", bg=BG,
                        fg=ACCENT, cursor="hand2",
                        font=("Segoe UI", 9, "bold"))
        name.pack(side="left", padx=4)
        name.bind("<Button-1>", lambda e: self.toggle_menu())
        if self.menu_open:
            menu = tk.Frame(self.frame, bg=BAR)
            menu.pack(fill="x", pady=2)
            for other in teams:
                mark = "•" if other["id"] == team["id"] else " "
                item = tk.Label(menu, text=f"{mark}  {other['name']}", bg=BAR,
                                fg=FG, anchor="w", cursor="hand2",
                                font=("Segoe UI", 9), padx=8, pady=2)
                item.pack(fill="x")
                item.bind("<Enter>", lambda e, w=item: w.config(bg=HOVER))
                item.bind("<Leave>", lambda e, w=item: w.config(bg=BAR))
                item.bind("<Button-1>",
                          lambda e, i=other["id"]: self.pick_team(i))
        mode = self.app.config.get("pokemon_display", "both")
        grid = tk.Frame(self.frame, bg=BG)
        grid.pack(anchor="w", pady=(2, 4))
        for index, pokemon in enumerate(team.get("pokemon") or []):
            cell = tk.Frame(grid, bg=BG)
            cell.grid(row=index // 3, column=index % 3, padx=4, pady=1)
            pic = tk.Label(cell, bg=BG)
            label = tk.Label(cell, text=pokemon, bg=BG, fg=ORANGE,
                             font=("Segoe UI", 8, "bold"))

            def show(image, pic=pic, label=label):
                pic.pack_forget()
                label.pack_forget()
                if image is not None:
                    pic.config(image=image)
                    pic.pack()
                label.pack()

            show(None)
            if mode != "names":
                image = self.app.sprites.get(pokemon, show)
                if image is not None:
                    show(image)

    def render_champions(self, data):
        if data.get("warning"):
            # the Exp. Amplifier reminder goes first, in red
            lines = [l for l in data["warning"].splitlines() if l.strip()]
            urgent = [l for l in lines if re.search(r"Exp\.? Amplifier", l)]
            rest = [l for l in lines if l not in urgent]
            for text, color in (("\n".join(urgent), RED),
                                ("\n".join(rest), AMBER)):
                if text:
                    self.text(self.frame, text, color,
                              ("Segoe UI", 8, "italic"), pady=(0, 4))
        self.text(self.frame, data.get("groupPrompt") or "Choose the champion:",
                  DIM, ("Segoe UI", 8))
        self.grid([(g["name"], lambda g=g: self.pick_group(g))
                   for g in data.get("groups", [])], 3, trainers=True)

    def restart_button(self, parent, text, colors=("#5a3b1c", "#ffcf8a",
                                                   "#7a5226")):
        """A bordered button that goes back to the champion list. `colors`
        is (background, text, hover background); orange by default."""
        bg, fg, active = colors
        frame = tk.Frame(parent, bg=BUTTON_BORDER)
        flat_button(frame, text, self.restart, bg, fg, active, "#ffffff",
                    font=("Segoe UI", 8, "bold"), padx=8,
                    pady=2).pack(padx=1, pady=1)
        return frame

    def nav_bar(self, possible=None):
        bar = tk.Frame(self.frame, bg=BG)
        bar.pack(fill="x", pady=(2, 2))
        back = tk.Frame(bar, bg=BUTTON_BORDER)
        self.button(back, "‹ Back", self.back).pack(padx=1, pady=1)
        back.pack(side="left")
        self.restart_button(bar, "↺ Restart").pack(side="left", padx=4)
        crumbs = [self.group["name"]] + [label for label, _ in self.trail]
        row = tk.Frame(self.frame, bg=BG)
        row.pack(fill="x")
        face = tk.Label(row, bg=BG)
        face.pack(side="left", padx=(0, 4))
        self.picture(face, "trainer", self.group["name"], 3)
        crumb = tk.Label(row, text="  ›  ".join(crumbs), bg=BG, fg=DIM,
                         font=("Segoe UI", 8), justify="left", anchor="w")
        crumb.pack(side="left", fill="x", expand=True)
        self.app.wrap_labels.append(crumb)
        self.app.wrap_off[crumb] = 32
        crumb.config(wraplength=max(60, self.app.current_wrap() - 32))
        self.team_list(possible)
        # a clear line between the trainer's info and the guide steps
        tk.Frame(self.frame, height=2, bg=BUTTON_BORDER).pack(
            fill="x", pady=(8, 4))

    def toggle_teams(self):
        self.teams_open = not self.teams_open
        self.later()

    def team_list(self, possible):
        """Accordion under the trainer: every team they can use, with each
        Pokemon's item, ability and moves. Teams the guide has ruled out are
        dimmed."""
        teams = load_e4_opponents(self.root, self.guide_id,
                                  self.group["name"])
        if not teams:
            return
        arrow = "▾" if self.teams_open else "▸"
        header = tk.Label(self.frame, bg=BG, fg=ACCENT, cursor="hand2",
                          text=f"{arrow} {self.group['name']}'s teams "
                               f"({len(teams)})",
                          font=("Segoe UI", 8, "bold"), anchor="w")
        header.pack(fill="x", pady=(2, 0))
        header.bind("<Button-1>", lambda e: self.toggle_teams())
        if not self.teams_open:
            return
        for team in teams:
            live = possible is None or team.get("team") in possible
            card = tk.Frame(self.frame, bg=BUTTON_BORDER)
            card.pack(fill="x", pady=(4, 0))
            inner = tk.Frame(card, bg=BAR, padx=6, pady=4)
            inner.pack(fill="x", padx=1, pady=1)
            title = tk.Frame(inner, bg=BAR)
            title.pack(fill="x")
            tk.Label(title, text=f"Team {team.get('team')}", bg=BAR,
                     fg=ACCENT if live else DIM,
                     font=("Segoe UI", 9, "bold")).pack(side="left")
            if possible is not None:
                tk.Label(title, text="possible" if live else "ruled out",
                         bg=BAR, fg=CHECK_GREEN if live else DIM,
                         font=("Segoe UI", 8)).pack(side="left", padx=6)
            for mon in team.get("pokemon", []):
                self.team_member(inner, mon, live)

    def team_member(self, parent, mon, live):
        row = tk.Frame(parent, bg=BAR)
        row.pack(fill="x", pady=(3, 0))
        # fixed 32x32 slot, so a picture arriving late doesn't move the row
        slot = tk.Frame(row, bg=BAR, width=32, height=32)
        slot.pack_propagate(False)
        slot.pack(side="left", anchor="n", padx=(0, 6))
        pic = tk.Label(slot, bg=BAR, bd=0)
        pic.pack(fill="both", expand=True)
        self.picture(pic, "pokemon", mon.get("pokemon", ""), 3)
        info = tk.Frame(row, bg=BAR)
        info.pack(side="left", fill="x", expand=True)
        top = tk.Frame(info, bg=BAR)
        top.pack(fill="x")
        tk.Label(top, text=mon.get("pokemon", ""), bg=BAR,
                 fg=FG if live else DIM,
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        if mon.get("item"):
            tk.Label(top, text=mon["item"], bg=BAR, fg=ORANGE,
                     font=("Segoe UI", 8, "bold")).pack(side="left", padx=6)
        if mon.get("ability"):
            tk.Label(info, text=mon["ability"], bg=BAR, fg=CHECK_GREEN,
                     font=("Segoe UI", 8), anchor="w").pack(fill="x")
        moves = tk.Label(info, text=" · ".join(mon.get("moves", [])),
                         bg=BAR, fg=DIM, font=("Segoe UI", 8),
                         justify="left", anchor="w")
        moves.pack(fill="x")
        self.app.wrap_labels.append(moves)
        self.app.wrap_off[moves] = 60
        moves.config(wraplength=max(60, self.app.current_wrap() - 60))

    def render_leads(self):
        self.nav_bar()
        self.text(self.frame, "Opponent led with:", DIM, ("Segoe UI", 8))
        self.grid([(e["label"],
                    lambda e=e: self.pick_step(e["label"], e["nodeId"]))
                   for e in self.group.get("entries", [])], 3)

    def render_steps(self, data):
        nodes = self.nodes = data["nodes"]
        self.follow_only_options()
        self.nav_bar(possible_teams(
            text for _label, node_id in self.trail
            for _kind, text in tidy_steps(resolve_node(nodes, node_id)[0])))
        branch = None
        last = len(self.trail) - 1
        # Only the latest choice is shown (plus anything followed
        # automatically after it); earlier steps are hidden. The breadcrumb
        # keeps the path and Back steps back through it.
        first = last
        while first > 0 and self.only_option(self.trail[first - 1][1]):
            first -= 1
        for index, (label, node_id) in enumerate(self.trail):
            if index < first:
                continue
            steps, branch = resolve_node(nodes, node_id)
            prev = ""
            current = index == last
            head_color = ORANGE if index == 0 else ACCENT
            heading = (f"Enemy sends out {label}" if is_pokemon_label(label)
                       else label)
            self.rich(f"▸ {heading}", head_color,
                      ("Segoe UI", 9, "bold"), pady=(4, 0))
            tidy = list(tidy_steps(steps))
            shown = []
            for pos, (kind, raw) in enumerate(tidy):
                nxt = tidy[pos + 1][1] if pos + 1 < len(tidy) else ""
                shown.append((kind, clean_step(raw, prev, nxt=nxt)))
                prev = raw
            for kind, text in team_lines_first(shown):
                if kind != "setup" and SWITCH_RE.match(text):
                    # a switch YOU have to make: stands out in cyan
                    self.rich(f"\u21c4 {text}", SWITCH,
                              ("Segoe UI", 9, "bold"))
                elif kind == "setup":
                    self.rich(f"» {text}",
                              ACCENT if current else DIM, ("Segoe UI", 8))
                elif kind == "note":
                    self.rich(f"· {text}", DIM,
                              ("Segoe UI", 8, "italic"))
                else:
                    self.rich(f"• {text}",
                              FG if current else DIM, ("Segoe UI", 9))
        if branch:
            self.text(self.frame,
                      branch.get("prompt") or "What happened?", AMBER,
                      ("Segoe UI", 8), pady=(6, 0))
            self.grid([(o["label"],
                        lambda o=o: self.pick_step(o["label"], o["nodeId"]))
                       for o in branch.get("options", [])], 2)
        else:
            self.restart_button(self.frame, "✓ Fight finished",
                                ("#1f4d2c", "#9be7a8", "#2e6b3e")).pack(
                anchor="w", pady=(6, 0))


# ----------------------------------------------------------------- the app
class Overlay:
    def __init__(self, root):
        self.root = root
        self.pages = load_tasks()
        self.config = load_json(CONFIG_FILE, {})
        self.sprites = Sprites()

        state = load_json(STATE_FILE, {})
        self.day = state.get("day", day_key())
        self.done = migrate_done(self.pages, set(state.get("done", [])))
        # Gyms are open by default; ticked (done) gyms are collapsed.
        self.closed = {child_key(p["name"], t, i)
                       for p in self.pages for t in p["tasks"]
                       for i in t["items"]
                       if child_key(p["name"], t, i) in self.done}

        ui = self.config.get("ui")
        ui = ui if isinstance(ui, dict) else {}
        self.ui_guides = dict(ui.get("guides") or {})
        self._ui_job = None
        if isinstance(ui.get("closed"), list):   # gyms opened/closed by hand
            self.closed = set(ui["closed"])
        first = next((i for i, p in enumerate(self.pages)
                      if p["name"] == ui.get("page")), 0)
        self.page_index = first
        self.page_name = self.pages[first]["name"]
        self.page_type = self.pages[first].get("type", "tasks")
        self.page_color = page_color(self.pages[first], first)
        self.tasks = self.pages[first]["tasks"]
        self.berry_plants = load_berry_plants()
        self.berry_view = None
        self.berry_images = {}
        self._title_state = None
        self._summary = None

        size = self.config.get("window_size", list(DEFAULT_SIZE))
        try:
            self.win_w = max(MIN_SIZE[0], int(size[0]))
            self.win_h = max(MIN_SIZE[1], int(size[1]))
        except Exception:
            self.win_w, self.win_h = DEFAULT_SIZE

        self.vars = {}
        self.rows = {}
        self.item_rows = {}
        self.wrap_labels = []
        self.wrap_off = {}            # label -> pixels taken beside it
        self.guides = []
        self.host = None              # frame the current page is built in
        self.page_cache = {}          # page index -> its built widgets
        self.shown = None
        self.trainer_images = {}
        self.expanded = set(ui.get("expanded") or [])  # open dropdowns
        self.collapsed = False
        self.page_menu_open = False
        self.rect = None              # game view rectangle on screen
        self.pinned = IS_WIN          # free-floating where we can't follow
        self.offset = list(PIN_OFFSET)  # pinned position from game top-left
        try:   # remembered from last time
            saved = self.config.get("pin_offset")
            if saved:
                self.offset = [int(saved[0]), int(saved[1])]
        except Exception:
            self.offset = list(PIN_OFFSET)
        self._save_offset_job = None
        self.free_pos = None          # (x, y) while unpinned
        self.start_time = time.time()
        self._topmost_n = 0
        self.launch_time = 0.0
        self.launch_after = None
        self.auto_tried = False
        self._last_pos = None
        self._dx = self._dy = 0
        self._press = (0, 0)
        self._resize_origin = (0, 0)
        self._grab = 0.0
        self._hold_top = None       # see hold_scroll
        self._hold_job = None
        self._thaw_job = None       # see freeze_body
        self._thawing = False

        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=BG)
        root.geometry(START_POS)

        self.build_main()
        self.update_title()
        self.build_body()

        saved_scroll = ui.get("scroll")
        if isinstance(saved_scroll, (int, float)) and saved_scroll > 0:
            self.root.after(300, lambda: self.canvas.yview_moveto(
                saved_scroll))
        if ui.get("collapsed"):
            self.root.after(500, self.toggle_collapse)

        self.main_frame.pack(fill="both", expand=True)
        self.apply_size()
        self.root.update_idletasks()
        self.tick()
        self.berry_tick()
        self.start_update_check()
        self.follow()

    # keys for the page currently shown
    def tkey(self, task):
        return task_key(self.page_name, task)

    def ckey(self, task, item):
        return child_key(self.page_name, task, item)

    # ---- close button and launching the game ----
    def make_close_button(self, parent, bg):
        return tk.Button(parent, text="x", command=self.quit_app, bg=bg,
                         fg=RED, bd=0, activebackground=bg,
                         activeforeground=RED, width=2,
                         highlightthickness=1, highlightbackground=RED,
                         highlightcolor=RED,
                         font=("Segoe UI", 10, "bold"), cursor="hand2")

    def show_launch(self, show):
        """Show the 'Launch PokeMMO' button in the title bar (only while the
        game is closed)."""
        btn = getattr(self, "bar_launch", None)
        if btn is None:
            btn = self.bar_launch = tk.Button(
                self.bar_frame, text="Launch PokeMMO",
                command=self.launch_game, bd=0, bg=BG, fg=ACCENT,
                activebackground=BAR, activeforeground=ACCENT,
                font=("Segoe UI", 8), cursor="hand2", padx=6)
            self._bar_launch_shown = False
        if show and not self._bar_launch_shown:
            btn.pack(side="right", padx=(0, 4))
            self._bar_launch_shown = True
        elif not show and self._bar_launch_shown:
            btn.pack_forget()
            self._bar_launch_shown = False

    def set_launch_text(self, text, state):
        btn = getattr(self, "bar_launch", None)
        if btn is not None:
            btn.config(text=text, state=state)

    def reset_launch_button(self):
        if self.launch_after is not None:
            try:
                self.root.after_cancel(self.launch_after)
            except Exception:
                pass
            self.launch_after = None
        self.launch_time = 0.0
        self.set_launch_text("Launch PokeMMO", "normal")

    def save_config(self):
        try:
            CONFIG_FILE.write_text(json.dumps(self.config, indent=2))
        except Exception:
            log_error(*sys.exc_info())

    def launch_game(self):
        """Start PokeMMO the same way double-clicking its exe would. Nothing
        is attached to the game: it runs as its own independent program."""
        from tkinter import filedialog
        path = self.config.get("game_path", "")
        if not path or not Path(path).exists():
            chosen = filedialog.askopenfilename(
                parent=self.root, title="Select PokeMMO.exe",
                filetypes=[("Programs", "*.exe"), ("All files", "*.*")])
            if not chosen:
                return
            self.config["game_path"] = chosen
            self.save_config()
            path = chosen
        if time.time() - self.launch_time < 30:
            return
        try:
            flags = 0
            if IS_WIN:
                flags = (subprocess.CREATE_NO_WINDOW
                         | subprocess.CREATE_NEW_PROCESS_GROUP)
            subprocess.Popen([path], cwd=str(Path(path).parent),
                             creationflags=flags, close_fds=True)
            self.launch_time = time.time()
            self.set_launch_text("Launching...", "disabled")
            self.launch_after = self.root.after(30_000,
                                                self.reset_launch_button)
        except Exception:
            log_error(*sys.exc_info())
            self.reset_launch_button()

    # ---- main window layout ----
    def build_main(self):
        self.main_frame = tk.Frame(self.root, bg=BG)
        self.build_bar(self.main_frame)

        # Page dropdown (opened by clicking the title); packed on demand.
        self.page_menu = tk.Frame(self.main_frame, bg=BAR)

        # Bottom strip: progress text and the resize grip.
        self.bottom = tk.Frame(self.main_frame, bg=BAR)
        self.bottom.pack(side="bottom", fill="x")
        self.progress = tk.Label(self.bottom, bg=BAR, fg=ACCENT,
                                 font=("Segoe UI", 9), padx=8, pady=2)
        self.progress.pack(side="left")
        grip = tk.Label(self.bottom, text="\u25e2", bg=BAR, fg=DIM,
                        font=("Segoe UI", 10), padx=4, cursor="size_nw_se")
        grip.pack(side="right")
        grip.bind("<ButtonPress-1>", self.start_resize)
        grip.bind("<B1-Motion>", self.resize)
        grip.bind("<ButtonRelease-1>", self.end_resize)

        # Scrollable content: a canvas with a thin dark scrollbar.
        self.content = tk.Frame(self.main_frame, bg=BG)
        self.content.pack(side="top", fill="both", expand=True)
        self.vbar = tk.Canvas(self.content, width=10, bg=BAR,
                              highlightthickness=0, bd=0)
        self.vbar.pack(side="right", fill="y")
        self.canvas = tk.Canvas(self.content, bg=BG, highlightthickness=0,
                                bd=0, yscrollincrement=20)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=self.on_yview)
        self.body = tk.Frame(self.canvas, bg=BG, padx=10, pady=6)
        self.body_id = self.canvas.create_window((0, 0), window=self.body,
                                                 anchor="nw")
        self.body.bind("<Configure>", self.on_body_configure)
        self.canvas.bind("<Configure>", self.on_canvas_configure)
        self.vbar.bind("<ButtonPress-1>", self.bar_press)
        self.vbar.bind("<B1-Motion>", self.bar_drag)
        self.vbar.bind("<Configure>",
                       lambda e: self.on_yview(*self.canvas.yview()))
        self.root.bind_all("<MouseWheel>", self.on_wheel)

    def on_body_configure(self, _event):
        box = self.canvas.bbox("all")
        self.canvas.configure(scrollregion=box)
        if self._hold_top is not None and box:
            # Keep the held position, or the nearest one the content allows
            # (Tk clamps it, e.g. to the top once everything fits). The page
            # passes through in-between sizes while it is rebuilt, so the
            # held value itself is kept rather than clamped.
            height = max(1, box[3] - box[1])
            self.canvas.yview_moveto(
                max(0.0, self._hold_top - box[1]) / height)

    def hold_scroll(self, top):
        """Keep content pixel `top` at the top of the view while the content
        is rebuilt and re-measured (pictures can arrive a moment later)."""
        self._hold_top = top
        if self._hold_job is not None:
            self.root.after_cancel(self._hold_job)
        self._hold_job = self.root.after(400, self.release_scroll)

    def freeze_body(self):
        """Stop Windows drawing the scroll area while the guide is rebuilt;
        thaw_body then shows the finished result in one go."""
        if not IS_WIN or self._thaw_job is not None:
            return
        try:
            ctypes.windll.user32.SendMessageW(
                self.canvas.winfo_id(), 0x000B, 0, 0)  # WM_SETREDRAW off
        except Exception:
            return
        # safety net, scheduled before anything else can fail
        self._thaw_job = self.root.after(1000, self.thaw_body)

    def thaw_body(self):
        """Lay out the rebuilt content while still hidden, then repaint it
        all at once."""
        if self._thaw_job is None or self._thawing:
            return
        self._thawing = True
        try:
            # finish the layout, including the resize events it queues
            # (they set the scroll area and position), while still hidden
            for _ in range(3):
                self.root.update()
            self.on_body_configure(None)
            self.root.update_idletasks()
        except Exception:
            pass
        self.root.after_cancel(self._thaw_job)
        self._thaw_job = None
        self._thawing = False
        try:
            hwnd = self.canvas.winfo_id()
            ctypes.windll.user32.SendMessageW(hwnd, 0x000B, 1, 0)
            # RDW_INVALIDATE | RDW_ALLCHILDREN | RDW_UPDATENOW
            ctypes.windll.user32.RedrawWindow(hwnd, None, None,
                                              0x0001 | 0x0080 | 0x0100)
        except Exception:
            pass

    def release_scroll(self):
        if self._hold_job is not None:
            self.root.after_cancel(self._hold_job)
        self._hold_top = self._hold_job = None

    @staticmethod
    def wrap_for(width):
        return max(120, width - 20 - 22 - 24 - 4)

    def current_wrap(self):
        width = self.canvas.winfo_width()
        if not isinstance(width, int) or width < 100:
            width = self.win_w - 10
        return self.wrap_for(width)

    def prune_wrap(self):
        alive = []
        for label in self.wrap_labels:
            try:
                if label.winfo_exists():
                    alive.append(label)
            except Exception:
                pass
        self.wrap_labels[:] = alive
        for label in list(self.wrap_off):
            if label not in alive:
                del self.wrap_off[label]

    def e4_team(self, teams, default):
        wanted = self.config.get("e4_team")
        return wanted if wanted in [t["id"] for t in teams] else default

    def set_e4_team(self, team_id):
        self.config["e4_team"] = team_id
        self.save_config()
        seen = list(self.guides)
        for rec in self.page_cache.values():
            seen.extend(g for g in rec["guides"] if g not in seen)
        for guide in seen:
            guide.refresh()

    def on_canvas_configure(self, event):
        self.canvas.itemconfigure(self.body_id, width=event.width)
        wrap = self.wrap_for(event.width)
        lists = [rec["wrap_labels"] for rec in self.page_cache.values()]
        if self.wrap_labels not in lists:
            lists.append(self.wrap_labels)
        for labels in lists:
            for label in labels:
                try:
                    label.config(wraplength=max(
                        60, wrap - self.wrap_off.get(label, 0)))
                except Exception:
                    pass

    def on_yview(self, first, last):
        self.ui_changed()
        first, last = float(first), float(last)
        self.vbar.delete("all")
        if first <= 0.0 and last >= 1.0:
            return  # everything fits; no thumb
        height = max(1, self.vbar.winfo_height())
        y1 = first * height
        y2 = max(last * height, y1 + 20)
        self.vbar.create_rectangle(2, y1, 8, y2, fill=DIM, width=0)

    def bar_press(self, event):
        self.release_scroll()
        height = max(1, self.vbar.winfo_height())
        first, last = self.canvas.yview()
        pos = event.y / height
        if first <= pos <= last:
            self._grab = pos - first
        else:
            self._grab = (last - first) / 2
            self.canvas.yview_moveto(pos - self._grab)

    def bar_drag(self, event):
        height = max(1, self.vbar.winfo_height())
        self.canvas.yview_moveto(event.y / height - self._grab)

    def on_wheel(self, event):
        if self.collapsed:
            return
        self.release_scroll()   # the user is scrolling: stop holding
        first, last = self.canvas.yview()
        if first <= 0.0 and last >= 1.0:
            return
        self.canvas.yview_scroll(-2 if event.delta > 0 else 2, "units")

    # ---- resizing ----
    def start_resize(self, event):
        self._resize_origin = (self.root.winfo_x(), self.root.winfo_y())

    def resize(self, event):
        x, y = self._resize_origin
        self.win_w = max(MIN_SIZE[0], event.x_root - x)
        self.win_h = max(MIN_SIZE[1], event.y_root - y)
        self.root.geometry(f"{self.win_w}x{self.win_h}")

    def end_resize(self, event):
        self.config["window_size"] = [self.win_w, self.win_h]
        self.save_config()

    def apply_size(self):
        if not self.collapsed:
            self.root.geometry(f"{self.win_w}x{self.win_h}")
        else:
            # collapsed: just the title bar, but keep the full width
            self.root.geometry("")
            self.root.update_idletasks()
            self.root.geometry(
                f"{self.win_w}x{self.root.winfo_reqheight()}")

    # ---- title bar and page dropdown ----
    def build_bar(self, parent):
        self.bar_frame = tk.Frame(parent, bg=BAR)
        self.bar_frame.pack(fill="x")
        self.make_close_button(self.bar_frame, BAR).pack(
            side="left", padx=(2, 0), pady=2)
        tk.Label(self.bar_frame, text=VERSION, bg=BAR, fg=DIM,
                 font=("Segoe UI", 8)).pack(side="left", padx=(4, 0))
        self.title_label = tk.Label(self.bar_frame, bg=BAR, fg=ACCENT,
                                    font=("Segoe UI", 10, "bold"),
                                    padx=4, pady=4)
        self.title_label.pack(side="left")
        self.update_title()
        self.collapse_button = tk.Button(
            self.bar_frame, text="-", command=self.toggle_collapse,
            bg=BAR, fg=FG, bd=0, activebackground=BG,
            activeforeground=FG, width=2)
        self.collapse_button.pack(side="right")
        self.update_info = None
        self.refresh_button = tk.Button(
            self.bar_frame, text="\u27f3", command=self.manual_update_check,
            bg=BAR, fg=FG, bd=0, activebackground=BG, activeforeground=FG,
            width=2, cursor="hand2")
        self.refresh_button.pack(side="right")
        self.update_button = tk.Button(
            self.bar_frame, text="Update available", command=self.do_update,
            bd=0, bg="#2e9e4f", fg="#ffffff", activebackground="#3cb862",
            activeforeground="#ffffff", font=("Segoe UI", 8, "bold"),
            cursor="hand2", padx=6)
        # Pinned: an upright pin stuck in. Unpinned: a loose, tilted pin.
        self.pin_images = {True: pin_image(ACCENT, 0),
                           False: pin_image(AMBER, 45)}
        self.pin_button = tk.Button(self.bar_frame, command=self.toggle_pin,
                                    bd=0, bg=BAR, activebackground=BAR,
                                    cursor="hand2", padx=4)
        self.pin_button.pack(side="right")
        self.update_pin_button()
        # Berry progress bar beside the page title, plus a water-drop alert.
        # Packed by update_title_progress only while berries are planted.
        self.title_bar = tk.Canvas(self.bar_frame, width=90, height=14,
                                   bg=TRACK, highlightthickness=0, bd=0)
        self.title_bar_shown = False
        self.drop_image = tk.PhotoImage(data=DROP_PNG)
        self.alert_label = tk.Label(self.bar_frame, image=self.drop_image,
                                    bg=BAR)
        self.alert_shown = False
        for widget in (self.title_bar, self.alert_label):
            widget.bind("<ButtonPress-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.drag)
        # The title both opens the page dropdown (a click) and drags the
        # window (a drag, while unpinned).
        self.bar_frame.bind("<ButtonPress-1>", self.start_drag)
        self.bar_frame.bind("<B1-Motion>", self.drag)
        self.title_label.bind("<ButtonPress-1>", self.title_press)
        self.title_label.bind("<B1-Motion>", self.drag)
        self.title_label.bind("<ButtonRelease-1>", self.title_release)
        # Coloured stripe under the title bar: tells the pages apart.
        self.accent_strip = tk.Frame(parent, height=3, bg=self.page_color)
        self.accent_strip.pack(fill="x")

    def update_title(self):
        many = len(self.pages) > 1
        self.title_label.config(
            text=self.page_name + ("  \u25be" if many else ""),
            fg=self.page_color, cursor="hand2" if many else "")
        strip = getattr(self, "accent_strip", None)
        if strip is not None:
            strip.config(bg=self.page_color)
        progress = getattr(self, "progress", None)
        if progress is not None:
            progress.config(fg=self.page_color)

    def title_press(self, event):
        self.start_drag(event)
        self._press = (event.x_root, event.y_root)

    def title_release(self, event):
        moved = (abs(event.x_root - self._press[0]) > 3
                 or abs(event.y_root - self._press[1]) > 3)
        if not moved and len(self.pages) > 1:
            self.toggle_page_menu()

    def toggle_page_menu(self):
        if self.page_menu_open:
            self.hide_page_menu()
            return
        for child in self.page_menu.winfo_children():
            child.destroy()
        for index, page in enumerate(self.pages):
            color = page_color(page, index)
            current = index == self.page_index
            base = HOVER if current else BAR
            row = tk.Frame(self.page_menu, bg=base, cursor="hand2")
            row.pack(fill="x", pady=(0, 1))
            stripe = tk.Frame(row, width=5, bg=color)
            stripe.pack(side="left", fill="y")
            label = tk.Label(
                row, text=page["name"], bg=base, fg=color if current else FG,
                anchor="w", padx=10, pady=5,
                font=("Segoe UI", 10, "bold" if current else "normal"))
            label.pack(side="left", fill="x", expand=True)
            for widget in (row, stripe, label):
                widget.bind("<Button-1>",
                            lambda e, i=index: self.switch_page(i))
            if not current:
                for widget in (row, label):
                    widget.bind("<Enter>", lambda e, r=row, l=label: (
                        r.config(bg=HOVER), l.config(bg=HOVER)))
                    widget.bind("<Leave>", lambda e, r=row, l=label: (
                        r.config(bg=BAR), l.config(bg=BAR)))
        self.page_menu.pack(fill="x", after=self.accent_strip)
        self.page_menu_open = True

    def hide_page_menu(self):
        if self.page_menu_open:
            self.page_menu.pack_forget()
            self.page_menu_open = False

    def switch_page(self, index):
        self.hide_page_menu()
        if index == self.page_index:
            return
        self.page_index = index
        self.page_name = self.pages[index]["name"]
        self.page_type = self.pages[index].get("type", "tasks")
        self.page_color = page_color(self.pages[index], index)
        self.tasks = self.pages[index]["tasks"]
        self.update_title()
        self.build_body()
        self.canvas.yview_moveto(0)
        self.ui_changed()

    def update_pin_button(self):
        self.pin_button.config(image=self.pin_images[self.pinned])
        cursor = "" if self.pinned else "fleur"
        self.bar_frame.config(cursor=cursor)

    def make_check(self, parent, var, command):
        """A checkbox with a green tick (the system one can't be recoloured)."""
        box = tk.Label(parent, width=2, bg=BAR, fg=CHECK_GREEN, bd=0,
                       highlightthickness=1, highlightbackground=DIM,
                       highlightcolor=DIM, cursor="hand2",
                       font=("Segoe UI Symbol", 10, "bold"))

        def sync(*_args):
            try:
                box.config(text="\u2714" if var.get() else "")
            except Exception:
                pass  # the box was destroyed

        def click(_event):
            var.set(not var.get())
            command()

        box.bind("<Button-1>", click)
        if hasattr(var, "trace_add"):
            var.trace_add("write", sync)
        sync()
        return box

    # ---- checklist widgets (built once per page; updated in place) ----
    def build_body(self):
        """Show the current page. Each page is built once and kept, so
        switching tabs only swaps which frame is visible (no flashing)."""
        if self.shown is not None:
            self.shown["frame"].pack_forget()
        rec = self.page_cache.get(self.page_index)
        if rec is None:
            frame = tk.Frame(self.body, bg=BG)
            self.host = frame
            self.vars = {}
            self.rows = {}
            self.item_rows = {}
            self.wrap_labels = []
            self.guides = []
            self.berry_view = None
            if self.page_type == "berries":
                self.berry_view = BerryView(self, frame)
            for task in self.tasks:
                self.build_task(task)
            rec = {"frame": frame, "vars": self.vars, "rows": self.rows,
                   "item_rows": self.item_rows, "guides": self.guides,
                   "wrap_labels": self.wrap_labels,
                   "berry_view": self.berry_view}
            self.page_cache[self.page_index] = rec
        else:
            self.host = rec["frame"]
            self.vars = rec["vars"]
            self.rows = rec["rows"]
            self.item_rows = rec["item_rows"]
            self.guides = rec["guides"]
            self.wrap_labels = rec["wrap_labels"]
            self.berry_view = rec["berry_view"]
        self.shown = rec
        rec["frame"].pack(fill="x")
        self.refresh_view()
        if self.berry_view is not None:
            self.berry_view.update()

    def build_task(self, task):
        name, items = task["name"], task["items"]
        key = self.tkey(task)
        var = tk.BooleanVar()
        self.vars[key] = var
        row = tk.Frame(self.host, bg=BG)
        row.pack(fill="x")
        self.make_check(row, var, lambda t=task: self.on_header(t)
                        ).pack(side="left", padx=(0, 4))
        rec = {"row": row, "title": None, "count": None, "items": None,
               "guide": None}
        self.rows[key] = rec
        if task.get("guide"):
            title = tk.Label(row, bg=BG, fg=FG, anchor="w", cursor="hand2",
                             font=("Segoe UI", 10))
            title.pack(side="left")
            title.bind("<Button-1>", lambda e, k=key: self.toggle_expand(k))
            box = tk.Frame(self.host, bg=BG)
            inner = tk.Frame(box, bg=BG)
            inner.pack(fill="x", padx=(22, 0))
            guide = GuideView(self, inner, task["guide"])
            self.guides.append(guide)
            rec.update(title=title, items=box, guide=guide)
            if key in self.expanded:
                box.pack(fill="x", after=row)
                guide.ensure_rendered()
            return
        if not items:
            tk.Label(row, text=name, bg=BG, fg=FG, anchor="w",
                     font=("Segoe UI", 10)).pack(side="left")
            return
        title = tk.Label(row, bg=BG, fg=FG, anchor="w", cursor="hand2",
                         font=("Segoe UI", 10))
        title.pack(side="left")
        count = tk.Label(row, bg=BG, fg=DIM, cursor="hand2",
                         font=("Segoe UI", 8))
        count.pack(side="left", padx=8)
        for w in (title, count):
            w.bind("<Button-1>", lambda e, k=key: self.toggle_expand(k))
        box = tk.Frame(self.host, bg=BG)
        rec.update(title=title, count=count, items=box)
        counter = 0
        for item in items:
            given = item.get("number")
            if given is False:
                number = None            # extra stops are not numbered
            elif isinstance(given, int) and not isinstance(given, bool):
                counter = number = given  # restart the numbering here
            else:
                counter += 1
                number = counter
            self.build_item(box, task, item, number)
        if key in self.expanded:
            box.pack(fill="x", after=row)

    def build_item(self, parent, task, item, number):
        key = self.ckey(task, item)
        var = tk.BooleanVar()
        self.vars[key] = var
        box = tk.Frame(parent, bg=BG)
        box.pack(fill="x", padx=(22, 0), pady=(2, 0))
        row = tk.Frame(box, bg=BG)
        row.pack(fill="x")
        self.make_check(row, var, lambda t=task, i=item: self.on_child(t, i)
                        ).pack(side="left", padx=(0, 4))
        title = tk.Label(row, bg=BG, fg=FG, anchor="w",
                         font=("Segoe UI", 10, "bold"))
        title.pack(side="left")

        # Everything below the gym name lives in one frame that is shown
        # while the gym is open and hidden once it is ticked off.
        details = tk.Frame(box, bg=BG)
        self.build_team(details, item)
        if item.get("info"):
            self.add_text(details, str(item["info"]), FG, ("Segoe UI", 8))
        if item.get("note"):
            self.add_text(details, item["note"], DIM,
                          ("Segoe UI", 8, "italic"))
        has = bool(parse_team(item.get("team")) or item.get("note")
                   or item.get("info"))
        self.item_rows[key] = {"title": title, "details": details,
                               "has": has, "shown": False, "text": None,
                               "label": (f"{number}  {item['name']}" if number
                                         else item["name"])}
        if has:
            title.config(cursor="hand2")
            title.bind("<Button-1>", lambda e, k=key: self.toggle_item(k))
        self.set_item_open(key, key not in self.closed)

    def set_item_open(self, key, is_open):
        """Show or hide a gym's details and update its arrow."""
        rec = self.item_rows[key]
        if rec["has"]:
            if is_open and not rec["shown"]:
                rec["details"].pack(fill="x")
                rec["shown"] = True
            elif not is_open and rec["shown"]:
                rec["details"].pack_forget()
                rec["shown"] = False
            text = f"{'v' if rec['shown'] else '>'}  {rec['label']}"
        else:
            text = rec["label"]
        if text != rec["text"]:
            rec["text"] = text
            rec["title"].config(text=text)

    def toggle_item(self, key):
        self.ui_changed()
        if key in self.closed:
            self.closed.discard(key)
        else:
            self.closed.add(key)
        self.set_item_open(key, key not in self.closed)

    def add_text(self, parent, text, color, font):
        label = tk.Label(parent, text=text, bg=BG, fg=color, font=font,
                         justify="left", anchor="w", wraplength=240)
        label.pack(fill="x", padx=(24, 0))
        self.wrap_labels.append(label)

    def build_team(self, parent, item):
        members = parse_team(item.get("team"))
        if not members:
            return
        mode = self.config.get("pokemon_display", "both")
        if mode not in ("both", "sprites", "names"):
            mode = "both"
        if mode == "names":
            for pokemon, move in members:
                line = tk.Frame(parent, bg=BG)
                line.pack(anchor="w", padx=(24, 0))
                tk.Label(line, text=pokemon, fg=ORANGE, bg=BG,
                         font=("Segoe UI", 8, "bold")).pack(side="left")
                if move:
                    tk.Label(line, text="|", fg=DIVIDER, bg=BG,
                             font=("Segoe UI", 8)).pack(side="left", padx=4)
                    tk.Label(line, text=move, fg=TEAM, bg=BG,
                             font=("Segoe UI", 8)).pack(side="left")
            return
        grid = tk.Frame(parent, bg=BG)
        grid.pack(anchor="w", padx=(24, 0))
        for index, (pokemon, move) in enumerate(members):
            member = tk.Frame(grid, bg=BG)
            member.grid(row=index // 3, column=index % 3, padx=4, pady=2,
                        sticky="n")
            sprite = tk.Label(member, bg=BG)
            name = tk.Label(member, text=pokemon, fg=ORANGE, bg=BG,
                            font=("Segoe UI", 8, "bold"))
            divider = tk.Frame(member, height=1, width=44, bg=DIVIDER)
            move_label = tk.Label(member, text=move, fg=TEAM, bg=BG,
                                  font=("Segoe UI", 8), justify="center",
                                  wraplength=80)

            def render(image, sprite=sprite, name=name, divider=divider,
                       move_label=move_label, move=move):
                for widget in (sprite, name, divider, move_label):
                    widget.pack_forget()
                if image is not None:
                    sprite.config(image=image)
                    sprite.pack()
                if mode == "both" or image is None:
                    name.pack()
                    if move:
                        divider.pack(pady=(1, 2))
                if move:
                    move_label.pack()

            render(None)  # name + move until the picture is ready
            image = self.sprites.get(pokemon, render)
            if image is not None:
                render(image)

    # ---- checklist behavior ----
    def set_done(self, key, value):
        if value:
            self.done.add(key)
        else:
            self.done.discard(key)

    def set_closed(self, key, value):
        self.ui_changed()
        if value:
            self.closed.add(key)
        else:
            self.closed.discard(key)

    def refresh_view(self):
        """Update ticks, counts, arrows and visibility in place (no
        rebuilding, so nothing flashes)."""
        for task in self.tasks:
            name, items = task["name"], task["items"]
            key = self.tkey(task)
            self.vars[key].set(key in self.done)
            for item in items:
                ckey = self.ckey(task, item)
                self.vars[ckey].set(ckey in self.done)
                self.set_item_open(ckey, ckey not in self.closed)
            rec = self.rows.get(key)
            if rec and rec.get("title") is not None:
                arrow = "v" if key in self.expanded else ">"
                rec["title"].config(text=f"{arrow}  {name}")
                if items and rec.get("count") is not None:
                    n = sum(1 for it in items
                            if self.ckey(task, it) in self.done)
                    rec["count"].config(text=f"{n}/{len(items)}")
        self.update_progress_text()
        self.update_title_progress()

    def update_progress_text(self):
        if self.page_type == "berries":
            text = self.berry_summary()
        else:
            total = len(self.tasks)
            n = sum(1 for t in self.tasks if self.tkey(t) in self.done)
            text = f"{n}/{total} done today"
        if text != self._summary:
            self._summary = text
            self.progress.config(text=text)

    # ---- berries ----
    def trainer_image(self, name, small=False):
        """A trainer's portrait (built into this script), 40px or 26px."""
        slug = trainer_slug(name)
        key = (slug, small)
        if key not in self.trainer_images:
            image = None
            data = TRAINER_PNG.get(slug)
            if data:
                try:
                    image = tk.PhotoImage(data=data).subsample(
                        3 if small else 2)
                except Exception:
                    image = None
            self.trainer_images[key] = image
        return self.trainer_images[key]

    def berry_image(self, slug, small=False):
        """The berry's picture (from the pictures built into this script)."""
        key = (slug, small)
        if key not in self.berry_images:
            image = None
            data = BERRY_PNG.get(slug)
            if data:
                try:
                    image = tk.PhotoImage(data=data)
                    if not small:  # 30px -> 45px
                        image = image.zoom(3).subsample(2)
                except Exception:
                    image = None
            self.berry_images[key] = image
        return self.berry_images[key]

    def find_plant(self, pid):
        return next((p for p in self.berry_plants if p["id"] == pid), None)

    def save_berries(self):
        try:
            BERRY_FILE.write_text(json.dumps({"plants": self.berry_plants},
                                             indent=2))
        except Exception:
            log_error(*sys.exc_info())

    def berry_changed(self):
        self.save_berries()
        if self.berry_view is not None:
            self.berry_view.rebuild()
        self.update_progress_text()
        self.update_title_progress()

    def plant_berry(self, slug):
        self.berry_plants.append({"id": uuid.uuid4().hex[:8], "berry": slug,
                                  "planted": time.time(), "waters": []})
        self.berry_changed()

    def water_plant(self, pid):
        plant = self.find_plant(pid)
        if plant is not None:
            plant["waters"].append(time.time())
            self.save_berries()
            if self.berry_view is not None:
                self.berry_view.update_one(pid)
            self.update_title_progress()

    def remove_plant(self, pid):
        self.berry_plants = [p for p in self.berry_plants if p["id"] != pid]
        self.berry_changed()

    def berry_stats(self, now=None):
        now = time.time() if now is None else now
        return [(p, plant_status(p, berry_info(p["berry"], self.config), now))
                for p in self.berry_plants]

    def berry_summary(self):
        stats = self.berry_stats()
        if not stats:
            return "no berries planted"
        growing = sum(1 for _p, st in stats if st["state"] == "growing")
        ready = len(stats) - growing
        parts = []
        if growing:
            parts.append(f"{growing} growing")
        if ready:
            parts.append(f"{ready} ready")
        return " \u00b7 ".join(parts)

    def update_title_progress(self):
        """The berry bar beside the page title (shown on every page) and the
        water alert."""
        stats = self.berry_stats()
        notches = ()
        growing = [(p, st) for p, st in stats if st["state"] == "growing"]
        if growing:
            plant, soonest = min(growing, key=lambda ps: ps[1]["ready_in"])
            fraction = soonest["progress"]
            color = progress_color(fraction)
            text = fmt_duration(soonest["ready_in"])
            notches = tuple(water_notches(
                plant, berry_info(plant["berry"], self.config), time.time()))
        elif stats:
            fraction, color, text = 1.0, CHECK_GREEN, "ready"
        else:
            fraction, color, text = 0.0, CHECK_GREEN, "no berries"
        alert = any(st["state"] == "growing" and st["water_in"] is not None
                    and st["water_in"] <= 0 for _p, st in stats)
        state = (round(fraction, 3), color, text, alert, notches)
        if state == self._title_state:
            return
        self._title_state = state
        if stats and not self.title_bar_shown:
            self.title_bar.pack(side="left", padx=(4, 0),
                                after=self.title_label)
            self.title_bar_shown = True
        elif not stats and self.title_bar_shown:
            self.title_bar.pack_forget()
            self.title_bar_shown = False
        draw_bar(self.title_bar, fraction, color, text, default_w=90,
                 default_h=14, notches=notches)
        if alert and not self.alert_shown:
            self.alert_label.pack(side="left", padx=(6, 0))
            self.alert_shown = True
        elif not alert and self.alert_shown:
            self.alert_label.pack_forget()
            self.alert_shown = False

    def berry_tick(self):
        """Once a second: refresh countdowns and bars in place."""
        try:
            if self.berry_view is not None:
                self.berry_view.update()
            if self.page_type == "berries":
                self.update_progress_text()
            self.update_title_progress()
        except Exception:
            log_error(*sys.exc_info())
        self.root.after(1000, self.berry_tick)

    def on_header(self, task):
        key = self.tkey(task)
        value = self.vars[key].get()
        self.set_done(key, value)
        for item in task["items"]:
            ckey = self.ckey(task, item)
            self.set_done(ckey, value)
            self.set_closed(ckey, value)  # done -> hidden, undone -> open
        self.save()
        if value:
            self.collapse(key)   # finished: fold it away (can be reopened)
        self.refresh_view()

    def on_child(self, task, item):
        ckey = self.ckey(task, item)
        value = self.vars[ckey].get()
        self.set_done(ckey, value)
        self.set_closed(ckey, value)      # done -> hidden, undone -> open
        key = self.tkey(task)
        was_done = key in self.done
        all_done = all(self.ckey(task, it) in self.done
                       for it in task["items"])
        self.set_done(key, all_done)
        self.save()
        if all_done and not was_done:
            self.collapse(key)   # the last item finished the section
        self.refresh_view()

    def collapse(self, key):
        rec = self.rows.get(key)
        if key in self.expanded and rec and rec.get("items") is not None:
            self.toggle_expand(key)

    def toggle_expand(self, key):
        self.ui_changed()
        rec = self.rows[key]
        if key in self.expanded:
            self.expanded.discard(key)
            rec["items"].pack_forget()
        else:
            self.expanded.add(key)
            rec["items"].pack(fill="x", after=rec["row"])
            if rec.get("guide") is not None:
                rec["guide"].ensure_rendered()
        self.refresh_view()

    def ui_changed(self):
        """Something about the layout changed: save it shortly (debounced)."""
        if self._ui_job is not None:
            try:
                self.root.after_cancel(self._ui_job)
            except Exception:
                pass
        try:
            self._ui_job = self.root.after(500, self.save_ui)
        except Exception:
            self._ui_job = None

    def save_ui(self):
        """Remember the page, open dropdowns, Elite Four progress, scroll
        position and collapsed state for the next start."""
        self._ui_job = None
        try:
            guides = dict(self.ui_guides)
            for rec in self.page_cache.values():
                for guide in rec["guides"]:
                    # Never-opened guides must not overwrite saved progress.
                    if guide.rendered or guide.group is not None:
                        guides[guide.guide_id] = guide.state()
            self.ui_guides = guides
            self.config["ui"] = {
                "page": self.page_name,
                "expanded": sorted(self.expanded),
                "closed": sorted(self.closed),
                "collapsed": bool(self.collapsed),
                "scroll": round(float(self.canvas.yview()[0]), 4),
                "guides": guides}
            self.save_config()
        except Exception:
            log_error(*sys.exc_info())

    def save_ui_now(self):
        if self._ui_job is not None:
            try:
                self.root.after_cancel(self._ui_job)
            except Exception:
                pass
        self.save_ui()

    def quit_app(self):
        if self._ui_job is not None:
            try:
                self.root.after_cancel(self._ui_job)
            except Exception:
                pass
        self.save_ui()
        self.root.destroy()

    def toggle_collapse(self):
        self.collapsed = not self.collapsed
        self.collapse_button.config(text="+" if self.collapsed else "-")
        self.ui_changed()
        x, y = self.root.winfo_x(), self.root.winfo_y()
        if self.collapsed:
            self.hide_page_menu()
            self.content.pack_forget()
            self.bottom.pack_forget()
        else:
            self.bottom.pack(side="bottom", fill="x")
            self.content.pack(side="top", fill="both", expand=True)
        self.apply_size()
        self.root.geometry(f"+{x}+{y}")
        self._last_pos = None

    def toggle_pin(self):
        if self.pinned:
            # Unpin: freeze where it is so it can be dragged.
            self.pinned = False
            self.free_pos = (self.root.winfo_x(), self.root.winfo_y())
        else:
            # Pin: remember this spot relative to the game view.
            self.pinned = True
            if self.rect is not None:
                self.offset = [self.root.winfo_x() - self.rect[0],
                               self.root.winfo_y() - self.rect[1]]
                self.remember_offset()
        self._last_pos = None
        self.update_pin_button()

    def remember_offset(self):
        """Save where the window sits relative to the game's top-left."""
        self.config["pin_offset"] = list(self.offset)
        self.save_config()

    def save(self):
        STATE_FILE.write_text(json.dumps(
            {"day": self.day, "done": sorted(self.done)}))

    def tick(self):
        today = day_key()
        if today != self.day:
            self.day = today
            self.done = set()
            self.closed = set()
            self.save()
            self.refresh_view()
        self.root.after(60_000, self.tick)

    # ---- following the game window ----
    def move_to(self, x, y):
        if (x, y) != self._last_pos:
            self._last_pos = (x, y)
            self.root.geometry(f"+{x}+{y}")

    # ---- updates from GitHub releases ----
    @staticmethod
    def version_tuple(text):
        return tuple(int(n) for n in re.findall(r"\d+", str(text))[:4])

    def start_update_check(self):
        if getattr(self, "_update_q", None) is None:
            self._update_q = queue.Queue()
        threading.Thread(target=self._update_check, daemon=True).start()
        self.root.after(6 * 3600 * 1000, self.start_update_check)

    def manual_update_check(self):
        self.cancel_refresh_reset()
        self.refresh_button.config(text="...", state="disabled", fg=FG)
        threading.Thread(target=self._update_check, args=(True,),
                         daemon=True).start()

    def cancel_refresh_reset(self):
        job = getattr(self, "_refresh_job", None)
        if job is not None:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass
            self._refresh_job = None

    def reset_refresh_button(self):
        self._refresh_job = None
        self.refresh_button.config(text="\u27f3", fg=FG)

    def _update_check(self, manual=False):
        try:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
                headers={"User-Agent": "PokeMmoHelper",
                         "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.load(resp)
            tag = data.get("tag_name") or ""
            if self.version_tuple(tag) <= self.version_tuple(VERSION):
                if manual:
                    self._update_q.put({"none": True})
                return
            asset = None
            for a in data.get("assets") or []:
                name = str(a.get("name", "")).lower()
                if name.endswith(".exe") and (
                        asset is None or "pokemmohelper" in name):
                    asset = a
            self._update_q.put({
                "tag": tag, "page": data.get("html_url"),
                "url": asset.get("browser_download_url") if asset else None})
        except Exception:
            if manual:
                self._update_q.put({"error": True})

    def update_poll(self):
        state = getattr(self, "_update_state", None)
        if state == "quit":
            self._update_state = None
            self.quit_app()
            return
        if state == "fail":
            self._update_state = None
            self.update_button.config(text="Update failed - retry",
                                      state="normal")
        q = getattr(self, "_update_q", None)
        if q is None:
            return
        try:
            info = q.get_nowait()
        except queue.Empty:
            return
        if info.get("none") or info.get("error"):
            # Green tick (up to date) or red ! (check failed) for 30 s; it
            # stays clickable and checks again when clicked.
            ok = bool(info.get("none"))
            self.cancel_refresh_reset()
            self.refresh_button.config(
                text="\u2713" if ok else "!", state="normal",
                fg="#3cb862" if ok else RED)
            self._refresh_job = self.root.after(
                30_000, self.reset_refresh_button)
            return
        self.cancel_refresh_reset()
        self.refresh_button.config(text="\u27f3", state="normal", fg=FG)
        self.update_info = info
        self.update_button.config(text=f"Update available ({info['tag']})")
        self.update_button.pack(side="right", padx=(0, 4))

    def do_update(self):
        info = self.update_info
        if not info:
            return
        can_swap = (IS_WIN and getattr(sys, "frozen", False)
                    and info.get("url"))
        if not can_swap:
            import webbrowser
            webbrowser.open(info.get("page") or
                            f"https://github.com/{GITHUB_REPO}/releases")
            return
        self.update_button.config(text="Downloading...", state="disabled")
        threading.Thread(target=self._download_update, args=(info,),
                         daemon=True).start()

    def _download_update(self, info):
        try:
            target = Path(sys.executable)
            new = target.with_name(target.stem + ".new.exe")
            req = urllib.request.Request(
                info["url"], headers={"User-Agent": "PokeMmoHelper"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                blob = resp.read()
            if len(blob) < 1_000_000 or blob[:2] != b"MZ":
                raise ValueError("downloaded file is not a program")
            new.write_bytes(blob)
            import tempfile
            bat = Path(tempfile.gettempdir()) / "pokemmohelper_update.bat"
            bat.write_text(
                "@echo off\r\nset n=0\r\n:retry\r\n"
                "timeout /t 1 /nobreak >nul\r\n"
                f'move /y "{new}" "{target}" >nul 2>&1\r\n'
                "if errorlevel 1 (\r\n set /a n+=1\r\n"
                " if %n% lss 30 goto retry\r\n exit /b 1\r\n)\r\n"
                f'start "" "{target}"\r\n(goto) 2>nul & del "%~f0"\r\n')
            env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
            env.pop("_MEIPASS2", None)
            subprocess.Popen(["cmd", "/c", str(bat)], env=env,
                             creationflags=0x08000000 | 0x00000008,
                             close_fds=True)
            self._update_state = "quit"
        except Exception:
            log_error(*sys.exc_info())
            self._update_state = "fail"

    def follow(self):
        try:
            self.sprites.poll()
            self.update_poll()
            self.follow_once()
        except Exception:
            log_error(*sys.exc_info())
        self.root.after(250, self.follow)

    def follow_once(self):
        """Windows only: sit at the pinned spot on the game window when it is
        open, and always stay visible and on top."""
        if not IS_WIN:
            return
        found = find_game_window()
        if found is None:
            self.rect = None
            self.show_launch(True)
            if self._last_pos is None:
                self._last_pos = (0, 0)   # marks "start position applied"
                if self.free_pos is not None:
                    self.root.geometry(
                        f"+{self.free_pos[0]}+{self.free_pos[1]}")
                else:
                    self.root.geometry(START_POS)
            if (self.config.get("auto_launch") and not self.auto_tried
                    and time.time() - self.start_time > 2
                    and Path(self.config.get("game_path", "")).is_file()):
                self.auto_tried = True
                self.launch_game()
        else:
            self.auto_tried = True
            self.show_launch(False)
            self.rect = found[0]
            if self.pinned:
                self.move_to(self.rect[0] + self.offset[0],
                             self.rect[1] + self.offset[1])
        self._topmost_n += 1
        if self._topmost_n % 8 == 0:   # re-assert on top every ~2 seconds
            try:
                if self.root.state() != "normal":
                    self.root.deiconify()
                self.root.attributes("-topmost", True)
            except Exception:
                pass

    def start_drag(self, event):
        self._dx, self._dy = event.x, event.y

    def drag(self, event):
        if self.pinned:
            return
        x = self.root.winfo_x() + event.x - self._dx
        y = self.root.winfo_y() + event.y - self._dy
        self.root.geometry(f"+{x}+{y}")
        self.free_pos = (x, y)
        if self.rect is not None:
            self.offset = [x - self.rect[0], y - self.rect[1]]
            if self._save_offset_job is not None:
                self.root.after_cancel(self._save_offset_job)
            self._save_offset_job = self.root.after(500, self.remember_offset)


# Small water-drop picture (14x18 PNG, base64) for the "needs water" alert.
DROP_PNG = "iVBORw0KGgoAAAANSUhEUgAAAA4AAAASCAYAAABrXO8xAAAAe0lEQVR4nGMwnvmfgRxMliZCGvmhmGSN8VBMkkaQTfehGKutuDT2A/F/KO4nVqM9kiYYtiekEeSn91g0vkf3LyGbcNqMrPE8ERrPo2isOPFfHoj/I2M8muWRNdqToNGechvJ9iOloUp2PMIwyA/5QLwfivNh/iKkkSgMANRpJ8tPsf+XAAAAAElFTkSuQmCC"

# Berry pictures (30x30 PNG, base64) from the FarmOracle data folder.
BERRY_PNG = {
    "aguav": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAG1BMVEX///8xMTFz1kpS"
        "lEKM70q91lLm72tKY0prvUqRU4s4AAAAAXRSTlMAQObYZgAAAKxJREFUeNqt0LEKgzAQBmB9A2ModD5L6GpDbOdy"
        "0LmEE2crR1eF4gNIi4/dJRd1bv/tu59/ueSPUVummK2lNlZ5kReL1QFPQ7mwYhzOfdxW3OFoY6+ZEW9jv9SAiNci"
        "C65bMB0CBOsaDAOYY/COgBmMeYibD7fAxot9xa3htzj1xDM/3T2J9pY8iRNNk6OJSrFy1tGFMvF+tOSdj9bzq7G2"
        "XP1GaVuGWk7C3/IFb8MlUI5UPPUAAAAASUVORK5CYII="
    ),
    "apicot": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAKlBMVEX///8xMTHv73vO"
        "zmNrhL06SoSUrebF1u97Yxm93muMtUpahCFznDFSa6XuEOpEAAAAAXRSTlMAQObYZgAAAI1JREFUGNNjYKAHYBQU"
        "QOELKRuiCIiGBmkIIilPK0817kSoECsvSwnuXAiXFgfyI1ZOhPPTy9OA/FkwDSJpQL7rzjUIflpKiusuBN/Nzc0F"
        "mZ+SkuLiehrOZ3QBAtfTZ1D4vtFwPoOIi6/vXSQ+o+yVK3evHkTywN27d69uRPKg4N27gSg+FhQUpEvIAwCEYy0r"
        "5KezOgAAAABJRU5ErkJggg=="
    ),
    "aspear": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAHlBMVEX///8xMTH35lL/"
        "/2uEc0LOtUqtxbW13s7m1lqElIRsW6RjAAAAAXRSTlMAQObYZgAAAKdJREFUeNq10EEKwjAQBdDmBk1RwaU/OLhu"
        "hK4VPEChA2ZpFjmBxb1Q6AWyyG2NMG31AP279/mbmWKlaF3+EdffQht7q9qZyjRPrsI8qMzr3C1WsE2vQY/FOcBB"
        "vAvG2josJm9rgj+WMg+gQN4Pk4FAuWTxG/AEnKL4DpAHBhZzHmQmcbGP4zgyp262y4o8HaQynIt8KSTbGF3itpys"
        "NomFUujvv9bIB6mfKBdDaRC5AAAAAElFTkSuQmCC"
    ),
    "babiri": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAHlBMVEX///8xMTFrrTGl"
        "5krO95xaezpCUilKaymlhDHv1nsQF4vaAAAAAXRSTlMAQObYZgAAAJ1JREFUeNq90LEKAjEMBuC7N0gFwdWc4nyk"
        "0FkacJajtyvc7bZD8BEc3Xxc69DUewDN1C+0f5s2/6jWLL2yxkAL1TtP/eZZ3Z1E7g8oxwUTk3sVr0kSe7o1aofM"
        "6nYaHFr2CdQUO2b1GCii/TYeEClp/jxHQWHQwHAlifZYjNk5oi/eh3yFw60+aJzC4AzU+XPj/FnVHRdY/lDmL+oN"
        "6N8h799Yue0AAAAASUVORK5CYII="
    ),
    "belue": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAJFBMVEX///8xMTExcyFS"
        "nDGc3nNSOpyce+bOrf97WsWtnGu9tXvv5q0GXEDnAAAAAXRSTlMAQObYZgAAALlJREFUeNq10MENgjAUBmDqBC2g"
        "UW8VHADKAigLcDEuYO0E9Oyh5OkGMoAxesfELmdNaMsA+t++/u+lyQt+kwkhGGHviLE89qas2NDSGbGiWtcscz0J"
        "V7tDyvwCmnKIt7nr5wAQVpmllBz2NC2H4aOxUAkZPJOy4VwlmFobcojwMM6/EYI4A3DeArZ/i+ujNb3z+an7cX95"
        "NVoI52DZC93CKbBZ3JUGqJ1Rp9+gRtch3U0RT/NADP+SD/IeMvT2xpAdAAAAAElFTkSuQmCC"
    ),
    "bluk": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAIVBMVEX///8xMTF7zkK1"
        "c+9zUr06QnuEWs7mlP9CnEJCc0I6QmPlW7c1AAAAAXRSTlMAQObYZgAAALNJREFUeNq10bEKwjAQgGHzBona0tVu"
        "nS/iLLlD6BbIdXATaQbXDp27de3oKPigFuzVumu2j8AfLrf621H62+vd4s5os3QCdcy6mSaF2vdGqFqKWdGlEty0"
        "e58XQ7xM3gL5vO8+RuKsHyovdQzo72ld6XfO8akhvkZxaw+N5bgwgOXq9pieB3KAfH4epU8BKZQO9dRnRnYlihUS"
        "M2IgscUwKvEyTxgD7I2e5zUJiuSDfrSFF4sNKQdMbHgwAAAAAElFTkSuQmCC"
    ),
    "charti": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAFVBMVEX///8xMTGtnDHW"
        "vQjOrSH/7yn//714WiYlAAAAAXRSTlMAQObYZgAAAHpJREFUeNrFz9ENwzAIBNB4g9hRB4jJAuXUCVovEPmyQbz/"
        "CHE/Cp6g4e8hccB0V8UYZ1eIeYM7pI18uxPbh9UccLSz7OaUSzure2EtVP05CFmJ1cbzq6cPRm+IOxECxRDXpTqs"
        "+/pp1z12gejshiBH47RAVqO9/p+6AO+1FTFqcFZlAAAAAElFTkSuQmCC"
    ),
    "cheri": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAJ1BMVEX///8pawjW93ul"
        "5nN7vUoxMTGEQjHOWkLvY1L/nIz/3r3ea1K9SjG4vlwkAAAAAXRSTlMAQObYZgAAAL1JREFUGNNjYKACYBQUReEL"
        "KZkEIEsrGxu7IkubhAYhKxByBSpB5YMxTj5QM5gvADPfUVTIVYCBURWmwNhFyNVQAKaHLTRUUDnE2TQYakd4R6OS"
        "SWiIswqEz9o5sxHoPtYQKD991soOYUcGuHGRq1Z2NAI9yGgK48/o2H6UAW585MyOjvKjjIpBUOMjOjq6y4+yGsO8"
        "lL6ju7zmGEOoMZTPWl5efgbIDoGaxxBz5sxRkLhLANy9CSA6lApRAwDkky6ojWSXKAAAAABJRU5ErkJggg=="
    ),
    "chesto": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAIVBMVEX///8xMTHOlP+U"
        "c+Z7Wkrv1ms6QntjWq2EWs7FtWutrWsxIshiAAAAAXRSTlMAQObYZgAAAJhJREFUeNq90CEOwzAMBdD1BonU9gAO"
        "GI+lpXRgZLygZUskB08DPkJvMFBWKRrIKRfSJD3A9tnTlyzbp/9FHiWVKGokXlAUOg2GRGavQSFn9wYAixsHWuHA"
        "z902tWiyWwvn2p1V6HEp9qkl5sfuN9FrIMqeY3CGy/x5nPxS+TauH+ayXzfFQETZ7RruMW7VtYlXcfiGTPxBvvET"
        "KCH75nO8AAAAAElFTkSuQmCC"
    ),
    "chilan": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAG1BMVEX///8xMTGl5krW"
        "rUL/77WtjELv1ntaezprrTGSntoWAAAAAXRSTlMAQObYZgAAAItJREFUeNq1zTsOwjAQBNDkBhs+Ci1HiFb2DUhv"
        "mT1B8PSpqOk4Nh7ExuIAme55ZuVuv/Ty78O1VYPQG8+YpLu83EcAqX+vXscZZuNT3A+Y6rhu87moahL3CVn54PM7"
        "HRHkZ3AOLG6ex+rkzqxRpuZYHZpZL9nvb99rC81k+79EhEpxm1kmPQND7pAPaOclqfzT0BAAAAAASUVORK5CYII="
    ),
    "chople": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAHlBMVEX///8xMTGtMTHe"
        "QkL/UlL/vaX/jHu9eyHvrTr33lJJzFdpAAAAAXRSTlMAQObYZgAAAJZJREFUeNq1kLEZwiAQhZMNAim0xXMBeUzg"
        "nRv4uYHprYJtKjNBZFux4EgGyHU//4P7Hs1OY7otklsftCRwK7QysK8BS7cHo6vp8/POcMoIgwD6omWRzFQC/VWE"
        "4XFRDn+NsqH3QNaCwifKOijbT6SsufBhfk8E0fvHNH4JgGuKX0aC18rtnBI5U+vFNG3qm/hS1N/aZ34OOh8EuZYT"
        "wQAAAABJRU5ErkJggg=="
    ),
    "coba": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAGFBMVEX///8xMTExWnsx"
        "c60pzt6E9/9SpdZzve8S3wowAAAAAXRSTlMAQObYZgAAAIVJREFUeNq90NENwjAMBFCyQVImiDoBOYsFfExA3Qlo"
        "ugGsT/pRewLw35Psk+3Lv6qUkkOpzEANThDqzT2BtsKdBq2/3Fd5WO/L6TSP7s8WFto+XM804bq/7ZnPcfLeN9Ow"
        "otvSsscBYow4BUitYQiJ7D6osS0w2HJYiFbi2ON0p7/mN/UFGf8eV8l+ctcAAAAASUVORK5CYII="
    ),
    "colbur": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAElBMVEX///8xMTH/vff3"
        "a+bFKbX/lO+OXoeZAAAAAXRSTlMAQObYZgAAAItJREFUeNq1ztsNgzAMBdBkAzuFAQplAOTLAE3iAarU+69SpEIS"
        "BuD+Hfnp7gk7R70D+fXidchMzSMkTZ0HTVtp9hoheFc/NBbkdDQwZy3S6uFlm5mAzmlTMTS7AYssST91HSbEpOcD"
        "/os5ITMfDpYhUq/7RfJepmpmw39ZPbiOz94z+Yt3cG9yd+UHXlMWUtaJJDAAAAAASUVORK5CYII="
    ),
    "cornn": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAJ1BMVEX///8xMTGclGOc"
        "c1J71lJjtVLmpea9jNZjUoRSQmt7a6UxlFIxY1Kra+pqAAAAAXRSTlMAQObYZgAAAMNJREFUeNq1zzsSgjAQBuBw"
        "gyw+0AmN5AR4gzA5ghewAVsbHiWNprVBsLNRobOwig21HkpGSHy0jn+13/7bLPpL4JPG5MsUAwKsbVLw4TDXteNa"
        "fhxq9+kwjsR6qWqPWrEIRKrN8tUiygLcnXNWhIHIAgDlMoqKPO65Tw84q7aJn2ymbU8aF4Wf7B3c+sJHu/J4Mjsb"
        "Uo6rCoBPkHYKnHus803WhDdRD5FrLWdvNu5ENguGVGxbSnnG2qQGgBeRoebf8wBwvzbuPbONkgAAAABJRU5ErkJg"
        "gg=="
    ),
    "custap": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAIVBMVEX///8xMTH31mul"
        "hDHFQkLvUkLWezH3rXP/xaX/e3P/3s47F1G6AAAAAXRSTlMAQObYZgAAAKVJREFUeNq10NENAiEMBmDYAHKnA7AB"
        "uQkuQVzAhvBogriATUdQBzA5bgLdUmKA4ADXt6/906Rlm5WU/1RKdORKTbrLykFL3YhAs+CTKNljNsxsKB7hme7u"
        "JniJ7/z6XnKgkB/8+kkI5+qLX1JCF0XxFR7pRWTbeiIAwuaIBI6MqQ7gkGxoc2PRnWys+9kYTTTWNu+DCbkjqvnP"
        "svtFnha2+9k29QWXxCrj49GvbgAAAABJRU5ErkJggg=="
    ),
    "durin": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAIVBMVEX///8xMTHF95xz"
        "tUKl5mM6cxBKnDExWhn3zpTFrVqMaym8JU8BAAAAAXRSTlMAQObYZgAAAMxJREFUeNqtj7GOAiEURZ0/gNGdxFZX"
        "+9kH2su+bI3A2DvA1MYg2+5v2Fnsf+4mgGOvLyHh5J4beJPXDRmv9P9UP3eslrQi37eR8VjLKxmZWTV/iN/YgNea"
        "Fq7V2uPvEkqhQREx9Ciz/hUOZhNWbEESG6G52wstElNlGOA7x1PyZ1sfNgou/UfKpzxCd4loIPc7DRbtojtnZoe4"
        "QwDdlu243+NnsCLnoPkQB+dt8YX2qnOUFn/KjTNOjgs2bS/za+kLsmmTnRukSvj0/AHuHSv8x4OafgAAAABJRU5E"
        "rkJggg=="
    ),
    "enigma": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAG1BMVEX///9KSkoxMTH3"
        "9+bm3sXOvaWEhIS1tbW1pYxvC87eAAAAAXRSTlMAQObYZgAAAKFJREFUeNq1zzsOgzAMBuCmJ6iR0hmF0gvYOQCC"
        "ZOdVdaUipSeAnYljNwxxuADevvyOZV9OKqHUkdes6tODMyqpOcT4GtHGBqmXEYsPO9eLwzrh4VM/tzTALXyfZocG"
        "IA3+OqRC1sF3hz7uTPCzJTNI8w7OSwsggRd6+Nn+YeVt7U5uF93gtSlu19BvK1No+m0qjcdRl/gwumr2MFbieVb9"
        "AaxWHN5Ml5QhAAAAAElFTkSuQmCC"
    ),
    "figy": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAIVBMVEX///8xMTHW5nuM"
        "lEr374ycezrvlDG9a0L//9bm1pTOvXsmgmY7AAAAAXRSTlMAQObYZgAAAJ5JREFUeNqt0D0KwkAQBeDdG+xIBEmn"
        "nkCv4JJgmcYThCnSCSEPtg6yZ0iXQhbmlGKR/enzuo/Hm2LUftGm9OFc1veLKfy4Fq6WW1HPYnKePl8TQVR5XjfS"
        "sfd+Hrqtff3ZDGYz9362jURPbJveJju2bJ8unq8nZttmDjy2rWTGiCVZBwDiumQB4FaVDQLkHa1rCUCy0gRB8Q0i"
        "UnvkB90ILQ97T6WjAAAAAElFTkSuQmCC"
    ),
    "ganlon": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAG1BMVEX///8xMTGclM7F"
        "vffe1oSllFpKQnPW1q1za6XBhbqFAAAAAXRSTlMAQObYZgAAAKpJREFUeNq1kDEOgkAQReUG7GIMrYPFtuw01mhB"
        "bRwOgGHDAYjYAnGdY4txF/YC/O79/yf5md02EkLEIQJiHhgSNUC+xjUoHhJfiLKnqVHLwTP2NCFMnmWGLwT1ODre"
        "X3T5YxX/6/dOlRp4YezHa802WfhTvCvT3M6OtS2AiCoOGMBS6wYdzImYuRF+bzoSGW7meDGAWl45Sg2Zee5qsCUX"
        "uwt2sS/M/9pCX+jQJ/dcXJGyAAAAAElFTkSuQmCC"
    ),
    "grepa": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAHlBMVEX///8xMTFapSGM"
        "1iHvxUr/5jrevUr//3OcjEoxY1KqCddwAAAAAXRSTlMAQObYZgAAAIlJREFUGNNjYKAdEETlMhoimIKCggxCAnCu"
        "aGhohKCyIUxANLS8vNlSURiqgTE0HMg3EmSEyouA+JVKmgjlQH75zClQPmNqKFB/aWhoIoIPBmj8EBi/BcIPg/IZ"
        "xFzB0mlwfporiAvnS6RBAMx+RnR+G5ibCPeeSxuyNDBgBCXSMlBCBxggtIkDAOsQK/o2BpB3AAAAAElFTkSuQmCC"
    ),
    "haban": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAHlBMVEX///8xMTHvQkL/"
        "e3v/nJzWISGlKSljMTFSMUprOmP++lWeAAAAAXRSTlMAQObYZgAAAKRJREFUeNq1kEEKwjAQRc0NJhG7zxSj646I"
        "e3MBCyndGugFLOIBRCQ3aG5rKk4C7vtX83gfZpjVchESypjmtQVGRaQlStaK7Jm0zu36YC01wLypZ99cch0pBTXX"
        "W48JcQs/NrNNYR7pROSLp3140q3wI8Tp6NAxDzHGt3Md8P7w5by/6mN8De7KLLCf2ruDcp/xaJJm1lWHO8gsQUil"
        "/56V9BL5AIsAIT1/K5hJAAAAAElFTkSuQmCC"
    ),
    "hondew": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAG1BMVEX///8xMTHF/0pz"
        "xUr/70pSnEqU3kpKY0rOxUqMFHUUAAAAAXRSTlMAQObYZgAAAKNJREFUeNq10MEKwjAMBuD1DSwong1M7xt9gwa8"
        "Ope6B7DZeUiNLzC2x1bQdvYs5vaRn8Cf4l+jcypY5a52WVpLpb+I3N9qncIWQfq6jic2toEgYj5WjgAO936IceSy"
        "gb2P8TVyi0Am2XmLpaV0jr11PlmdvSP2x+TxisyGTkV0i2y6MVm6iWgeU8GthJdl8RxIZFi6z+HyXse64THp/B2R"
        "v84TtKwoNGxjoJIAAAAASUVORK5CYII="
    ),
    "iapapa": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAG1BMVEX///8xMTFzezH/"
        "73vvzpTvlDHOc0KtczHWtXvVSlWUAAAAAXRSTlMAQObYZgAAAK5JREFUeNqt0EEOgjAQBVB6A0qka8OicavTBVuh"
        "MexJDwDGHy7gARTSzLHFpK241tm9/zOZZLL/TS7yLcVx9+WiMVvLU9ucI4SUCx3oEbuSGNe62of23tMFRHXYL52j"
        "eiGi5J4sJ4ubc5W1M3XBcBVZ23YcPcxkrOXkoiUD5incV2oxjCcjefITfywUAB6Zg7O3vWYfLVZDe+TRGhiA5Exi"
        "VGu0+YbUGEIdk8Df5gXjCDEoQScUlwAAAABJRU5ErkJggg=="
    ),
    "jaboca": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAG1BMVEX///8xMTH372t7"
        "ezHOvSn//9alhDFjYymlnDHzzYdhAAAAAXRSTlMAQObYZgAAAJ9JREFUeNq1kDEOwjAMRckNEoQqZjdcIEmlrJAv"
        "tXOkHIClzAWGrhWV6LHJkKjpwlZvT/5+ln3Yr8QWGfG/XPUFM8H6e9E8UvUYCrWi9in5qnJOk7xmPl1k41XB0I13"
        "mHJcu1DjuwxZHkyA1Ro82YIBXuTmxDc5dloRbOK5dR9fA3n+/IYhaTqe/ZGBMa7LAVh0gq/XLdMybV7FY3eX+gE2"
        "aB3XWPUxWQAAAABJRU5ErkJggg=="
    ),
    "kasib": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAG1BMVEX///8xMTHmQr3/"
        "a861MZT//72tezH/peZrOmPnmMGZAAAAAXRSTlMAQObYZgAAAKtJREFUeNqtkD0OwjAMRtMbJOFHXXE9ZLaROrf1"
        "kLVHYIALdGCPItRjEwkTygzeXt7n2LL5YzX2mw/zRzlnmutc0fPZHW817/uF5HGpuruTcNhoxo7BVr3A1FNlz4Tl"
        "AxyUdwTTnQFPGgeM3UIwKntc175oUG5XSUyQYNC8xDIsAFj1EgsmQOX9kCjk8R03zvqQ80vrS5asWlviuNGmyRGc"
        "2bC0uouy01P+Xk+VVh77qjEV1wAAAABJRU5ErkJggg=="
    ),
    "kebia": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAJFBMVEX///8xMTEpnCkx"
        "xTpS72MpaymErTG195yUxTqEc2NrWlLW/8VaRG+cAAAAAXRSTlMAQObYZgAAAKFJREFUeNq9z7ENwjAQBdB4A9uZ"
        "IDFSavtA1IFbALECckOXApPUKYyYICwQ45oBQZbOYQH43bvvO8nFnyIEF/yLCvVRL1wh4iabKbT2tD+QJVjvR+S5"
        "NtdbGFGToeljuL9aem5cnMI5u9z2MXrEltabYZoviBWtu0d0Cuk+M+45d7DeLf7UALrIdh0AVOQ6EfL3yhpSTZGJ"
        "PJtJIg2ESPxB3qYyKOUcXYuHAAAAAElFTkSuQmCC"
    ),
    "kelpsy": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAGFBMVEX///8xMTFzY+aM"
        "1v9aUmNjUpxzrf/FxXuWhs/6AAAAAXRSTlMAQObYZgAAAJRJREFUeNqt0DEOwjAMBdDmBjFVxdygcoEvMUNEwgxK"
        "2Cmtd6RKXJ8w4JgZ/vYs2fpy88eQhiFyVnmFMCgbICTtO1K0ld2VmW/iDtgqG+A9OIs3YJ57K9sXZh73H7aAK7b1"
        "GDCx1GkxRew8SdXJJ+ZDLRNccV/thxy1c85xtGI65uRIaJZnoELJenk0Oif6tpFP/p4XaqwdqNOggAwAAAAASUVO"
        "RK5CYII="
    ),
    "lansat": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAIVBMVEX///8xMTGl5r2M"
        "zqWEOiH3xa33vaXejGsxc0pjpXvFa0o0DOPRAAAAAXRSTlMAQObYZgAAAK5JREFUGNNjYKAGYETjCwmg8oXR+Ypo"
        "+ieJsDgKwhU5Skgat4alQ/ksgmGVE5VnpFdB+Yyh6UubjC3bF8KUi5WHNltaTodrF68KbZ48c8YSuHFLQzNnzpwB"
        "V+++LCwDmS9WlpbWORNhnvjy9LSMjnI4X2R5WVlZefkqB5hrq8rT08urVsEsZCxfVQ6UroJpcC9fCJQVWQXjiy8R"
        "FC8vZHAUhPIFHYBa0EJEkIE2AADqgjLNs9ZTfgAAAABJRU5ErkJggg=="
    ),
    "leppa": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAJFBMVEX///8xMTFa1lJC"
        "nEIxc0L/lDHv5mPmczHOSjG1pWP/3jGcUjpF8pr2AAAAAXRSTlMAQObYZgAAAI1JREFUeNq10LENwkAMhWHfBnZI"
        "kFLGsADxBCcmSGGxwSkMgERLdxKbZMpccUQv1PB3X2Nbpj8miCByQTZq6LaQwY0pMpw0EnoceGfjIAyOZcGwSUI8"
        "2Khc2XkbTfUzslums8lV64HBl8mERIir3Qu2ju63/AI//LlzLoH7Oc8Zb0tpfoOpT/fvV9GvWgHfeBfWGGegYQAA"
        "AABJRU5ErkJggg=="
    ),
    "liechi": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAHlBMVEX///8xMTHWzpT3"
        "78X///elnIStUhD/rUrWczH/5qUsLaAFAAAAAXRSTlMAQObYZgAAAK9JREFUeNq90D0SgjAQBWC5Afg31ET3AFmg"
        "FzI5QNAcQDDBksKQlsbhBDreVgsSuYBu9yUvmTe7+MsEURTNuSSsnB2sK8YbFvprrE7a7A7Oq/zG+EUULrDRzbGk"
        "e+hcXDFeI8phcpal3CBCGzrXhSL02k2ucpNSkWj7NSIoOU5WqGuE1939Z4g+Izyta7wlIBLoR99HUDhL6x1IBY82"
        "/jz3hVVvh9A7iMfYp/1+fjJvij0oKgfPQ4gAAAAASUVORK5CYII="
    ),
    "lum": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAFVBMVEX///8xMTFSpUqU"
        "3kql/0pKY0pzxUoKzJbwAAAAAXRSTlMAQObYZgAAAH1JREFUeNrFz9ENgzAMBFDYIKZiAB9igRxlAbIAQTAA7L9D"
        "TaXETNBa+Xmxz5Kb/5RIkCcJTaGyJRjpfsUpEeLtISVSq629cF9LoIvTwvcwV2fSItTijbQR92Emz+p8cZuBtezP"
        "gD0E9wi3Bb7Wwqa/rY97+j3f9A8R4y/qAyy9FO3FeN8jAAAAAElFTkSuQmCC"
    ),
    "mago": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAHlBMVEX///8xMTH/96Xe"
        "1nOtWkL/vZz/5pzme3P/lITFrWOl0cbVAAAAAXRSTlMAQObYZgAAAI5JREFUeNq90DEOwjAMBVBygwSK2OkJkJFQ"
        "9lTiAmm5QLNXApmegBll8m1xB/LTA8DfnvxlS978JU5T0bShH52Fz31K44TCPqkHu3YsNg/txzgVP6OyMt+VNzgs"
        "HnCgCeoXfOi0zrC5Kis3zJwZ93fzZaZsC4V89qfveHtsfSayMBGJw3YRebv1e7T8k3wASmMlzC6kRh8AAAAASUVO"
        "RK5CYII="
    ),
    "magost": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAHlBMVEX///8xMTFjzlLm"
        "hGP/vZz/5pwxnFIxY1L/pYytWkJZBvotAAAAAXRSTlMAQObYZgAAAIJJREFUGNNjYKAbEETlMSoJIHEZy8SR+IyC"
        "QorihQiuSKiYkrggXF7ENTSwvEg8ESbtEhoa6iKkWIjCF1OEqRd2cQ0NcXEURvDBwBnObwHzmw1hfAsQ18MYzjcG"
        "CjQbw/mMxhAwEY0Pd58wmGsJ5zNORlYO8jxQYCKy9wUFBQVoEugAC0EccHd4IjYAAAAASUVORK5CYII="
    ),
    "micle": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAElBMVEX///8xMTFKe0I6"
        "rTpCzkKM74wWxZvaAAAAAXRSTlMAQObYZgAAAGdJREFUeNq90NENwCAIBNC6gdoJjC6gdAPPDcr+qzQ0KeACvb+X"
        "0xA4/kpKaWOlER0bMIsyNPCNrs5gsdWLGbNbvRjOJyRU9LlwUvx8CW1+JiHZd3pTdo+o1trst8lCt22oSrvFT3kA"
        "0NcWpZyylbgAAAAASUVORK5CYII="
    ),
    "nanab": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAHlBMVEX///8xMTH/74TW"
        "xVr/tYR7WkKlnEr/3oTOa2vvlGuOaPAeAAAAAXRSTlMAQObYZgAAAKVJREFUeNqt0EEKwjAQBdDmBglW7dYE3DdC"
        "TjBqu68HaCs9gZB1oKXxBh7XRDJJ61aHbB78zzDJ/jZsTcLZlzld5+VhKZZtJE3kginVxnInZF/u0CQfOn5sCQ3c"
        "axgULzGda/2ATiiKvnqrE8bPswtc7j260eACEA3V7G1CvZgazzq6AajcQ29HsCOAxXXE3hzr5OlDk457wsuaxW8U"
        "NhAbjCF/nTemHSjobXDwbwAAAABJRU5ErkJggg=="
    ),
    "nomel": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAGFBMVEX///8xMTH392Nj"
        "YxDm5kqlpQj///fFxSnVkHa4AAAAAXRSTlMAQObYZgAAAHxJREFUeNq1zz0KgDAMBlCLF2h6hBA6+3cCKXQWB3cH"
        "9w4l17dFSCrOZsojHyHpfiwzvAiLfdnt2vcAMyWlw7gfoFG8KM9C40/EuImnC5Eau7M6ybYaD2rj8WMKvKnrmK24"
        "MHAW92tJc2quK8xWXQlCQ3GEQjE/0N+7/+oGxGEYW/8MpzwAAAAASUVORK5CYII="
    ),
    "occa": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAHlBMVEX///8xMTHvczG9"
        "YyH/lGPee0L/vZR71pwxa0o6pWODVbXPAAAAAXRSTlMAQObYZgAAAH1JREFUeNrFz7ENw0AIBdDcBnd2kdofLwCX"
        "CSzY4JQJLM+QNVJm26AU4CyQUPH0v5C4/G/aeW+1PGpyNb6+wuVmY+NnxLPed+1Zn+zYDVnHOHSAw6Rqmp7cY6Ml"
        "LKvHZ0MA4TQBlPfnT0xpj7ufDwt1LDVcuoDr17fN+ZN5A45CE8GhjORzAAAAAElFTkSuQmCC"
    ),
    "oran": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAHlBMVEX///8xMTFSUoTm"
        "7/9ra71Spfda1v+cpb29xf9Se87riGYFAAAAAXRSTlMAQObYZgAAAJRJREFUeNq9z0EKwkAMBdDODTLFXmCooEvp"
        "CSzBvWX+QLdCcwBX3aoL3Sr2vo4yYewF+ncvnxBSLBVLM5bN7k/Gnm8NZVbddXPProKMzl2UxoucxseW1EFkcG56"
        "Jq+ChAHAUddxEGDtQalHCmkPeAB97jvEvJPNhB9rNb+Annlf6EH+JtvUzC23lJ8v48DOHraRC+QDsO0jsl0rIfMA"
        "AAAASUVORK5CYII="
    ),
    "pamtre": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAALVBMVEX///8xMTGc1oxz"
        "a0rv3rUxczHOvZSMe721peZSSilaSoxzY6VztWOllGtCMXO3RJk2AAAAAXRSTlMAQObYZgAAALhJREFUGNNjYKAa"
        "YDQQQOU7onJFRQyQuIJCqoEI9YyCSkpnkLji5aExhxB88Y72rWdi4HzGio6O0lA4n9G8oqO9fDecLzK9vL28fPtW"
        "OH9WeXl1dfUuKJ/RbbKx+fbtu+H8NDOX2dXVu9fB+ddyZ+3evWshzPi0tFxjY6tVD2HWi6VddnGZtQ7uHNm7l9Ny"
        "58GlgfxruZeNLRG+uXv3rlnuRThf7CJQ4CLCN7kCgoKCSGEnSL04YQAA6cQ6h0ZqCX0AAAAASUVORK5CYII="
    ),
    "passho": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAG1BMVEX///8xMTExY6XO"
        "pTrv5mspa9ZChO97rf+Ec0KC0+6lAAAAAXRSTlMAQObYZgAAAJRJREFUeNq90EEKgzAQBVC9QdIiuLZJ9zJduI35"
        "QtaBeACh4w10XdKDt4sYcwL/7jF8mJnqmkgpStYPGFGw4Q796du6LbAij5/7rkrzur07yoWGmReF0zOzQnatw8y+"
        "8BT+UbaXyaP2wTsaSCRPKijEePg1QgNDHA4Do4ORqV/dLeC+Jq/fEiz1p+uW6CPKe9M7LsgPbp4e2HYpp1wAAAAA"
        "SUVORK5CYII="
    ),
    "payapa": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAJFBMVEX///8xMTG172tz"
        "rSFKYymMKXPFKZz3Qt5jY2P/hOb/re97OmspJ+zHAAAAAXRSTlMAQObYZgAAAJtJREFUeNqtj70NwjAQheMNbJDT"
        "UHkEwBOwAUUQbYq8K9L7RMkUiBVoYUAuwhc7tPC6T34/5+ZfMnbJq/DF0dmFPx5qx3Xz2lVsOoyx8ntiPLdWX13L"
        "nMZ9yOgBEl6H2cxg9Pkkc+I7J+Coabo8bgyctfvDg7a3JH6GawqLYGeGYCrsQVzi0o9JvaLsA3ldA1C73j/kNf2f"
        "4s96A4t2LD7tJAliAAAAAElFTkSuQmCC"
    ),
    "pecha": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAHlBMVEX///8xMTH/xZz/"
        "5pzvlHP/tXNjzlKtWkIxc0JavUI+qcfLAAAAAXRSTlMAQObYZgAAAIpJREFUGNNjYKANYBQUROYKChkrCSBxlZSN"
        "jRQRipWUlIyVEHygYhCAaWAEKlY2QucrGzlC+SJKIPXIfDBQdYFqEAkC80PgfFeINJTPmO7iAubC+IkuJS5gAFUv"
        "Jgjhw8yXyBQE8wsRfgUJCCI8KCnRKCg4QwApNDpmzpwpgBwgnTNRAogBNbyoBgAOZRwUFboypQAAAABJRU5ErkJg"
        "gg=="
    ),
    "persim": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAIVBMVEX///8xMTFz3lJK"
        "rUIxY0L/zpz/76Vja0LmnHP/vYS9c1IBcm6GAAAAAXRSTlMAQObYZgAAAJ9JREFUeNq1kDEOwjAMRckNMFI7MLa9"
        "AA0Sc4ErmDbs8Y7aqqwMICsHQVFPSRac9AD19qz/v+y/WWcULHlXbJdcNpBulD5eDqm9P1cNCGftUBdXyVA32+qq"
        "LoWJ7NTr059zIsJpEH+Ogc0rxnUfwo7lgP2XrHEJhzwfWb3J3tmJXyEGtRfO0LBnL/LRsGMHImfmmSE+9+T5kfYD"
        "ELpYaX6i4CjO73RvXAAAAABJRU5ErkJggg=="
    ),
    "petaya": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAJFBMVEX///8xMTGMSjHW"
        "vZSljGNjMRDFe1L3pXv/1sXF74yEvWtrpVIqxpeOAAAAAXRSTlMAQObYZgAAAMRJREFUeNq1z7EOgjAQBmBq4t4K"
        "wTjSirpTElYIFUcF0VmG4ioOdRdjn8HZzcnZl9PhBN31tu/+f7gz/jUIkS/3sgh/pnzJWmPTjChvjByTMT92YEE6"
        "wqJHEXlgyxTcLUXGwTYTNV9XNAajmV/UKROhAQ5Oo4r5YgMea00DTxQU+n2t9bFOJ17rvdptz+++fVBK2VJi8KpM"
        "lKpo8193cH0VvOZ+dLknSk7jEDy49aayyHPcxAvpDl8p+IGNBSFk/jYxfjdPAFQqqve9uEUAAAAASUVORK5CYII="
    ),
    "pinap": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAJFBMVEX///8xMTFSvVpK"
        "a0J73lqUjFr35krOtVK9tWP/95TezlJra0INnLHDAAAAAXRSTlMAQObYZgAAAMJJREFUeNqt0D0OgkAQBWD3BqyJ"
        "aIucQJYbrBcgZiHUhhHtKDZTUEP0AoQ5gbZUXs9NnPWn1um+vJlXzOxfIwL55flmLb+cxHHw3pZaqbdFuNdpoiLP"
        "FXTxVqkNOyypUjrVkuNjTsPOLURsunXUJSrjvgXRWIIxzexlukB9wmcuDueSeoCDN1BHFcDVuz+OgzsvLDuHGlzc"
        "cp8wufMJ24n7lwbyKyIG3hatMWi9hUU394zpFgrn6eMbC4MNk98jmb/OA7XOOPTpObScAAAAAElFTkSuQmCC"
    ),
    "pomeg": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAG1BMVEX///8xMTFatVL/"
        "lDH/3lLOSjHmczExY1KEOjG/SWI1AAAAAXRSTlMAQObYZgAAAIVJREFUeNq10EEKAjEMBdDmBs1IYbae4Y/1APYC"
        "RTLMVsTZ6w1czL0thUmIa/27Rz4hJPwxFD0H7+Hopvx6mpgTztE4lbxCTSjlku/qA6YCrOYmIO+mazeqGt7zl6Xz"
        "pE698FBvMjfKvj/JJi1qYlkaq50vvEiN6pFvwsZA4ztF/zkOv8kHGb8cAas3L7oAAAAASUVORK5CYII="
    ),
    "qualot": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAHlBMVEX///8xMTHe1nPv"
        "93u9tWP/1oT/94ScjErvnHP3vXs9rGHoAAAAAXRSTlMAQObYZgAAAJlJREFUeNq90DEOwjAMBdDmBkmgYsatlL3m"
        "ApQglR0jZqRmbxdYmcgBGDgurhQ3vQD87fnLHlz8KcrowmQai3uDeiYB4ghidQkVImylLkO4ITbDXLNTL+6hAdkv"
        "2UQ+m0JPdK7r5DVNufoueXWc/IlR7D07xme6vznsuM5W1endxYVH3z7YWuxaYL/Ehb07tlk8wzqhTJi/yBd31Cj/"
        "vW4/8gAAAABJRU5ErkJggg=="
    ),
    "rabuta": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAIVBMVEX///9SUiExMTH3"
        "787FvYSUjFIxYxmM1nNCjClzvVqt74x+yxWsAAAAAXRSTlMAQObYZgAAAMJJREFUeNqtyjEOgjAUxvFHTyAU91Ig"
        "OgPhAIDsgCSukoCuToTRQVJOAD0Biae0ClQOwH/7ve/BBmmAAIy/TWJSxaHSyMHYDB1pxcNh6BGQYRxG+dqCVSGp"
        "Yje+s1Y+ZLp34ZwtVmzD7/gwFHS6IP8h5o5ds8lmXHdc7OVJ+5nexrrhXXsOYOrwrnsxuxGZfBybZii9KN3Nrnv+"
        "ylx3JiDGGXuqOZEWtaW6GOiX+xRktCr1hMI/W08CWGVZxFgbIdimD60sMflA/34bAAAAAElFTkSuQmCC"
    ),
    "rawst": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAHlBMVEX///8xMTFa1lJC"
        "nEIxa0KElK1jWnuU1taU5uaMtdYOPb1dAAAAAXRSTlMAQObYZgAAAKZJREFUeNq1z8ENgzAMBdBkAzsRba8NE6Bk"
        "ASoW4GDUK0IMwKFyJ2joAIiOWyolIR2Af3v298HikCD+05T5QBrTlAjJqmyMuV2za7W5hlgHqYxrbBxIUQwOtXVV"
        "PDgPBaF1Nhbuw8VPmZ+v2fe2tlXye9uDTv7MrF3yiWfPGlsZXDA/JqReQvDKzAu1UgSPKy8dAUTTL+3+L3VEPewe"
        "iTAwPIzioHwB8xskJcOD4QAAAAAASUVORK5CYII="
    ),
    "razz": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAHlBMVEX///8xMTH/rSne"
        "WjGE70IpWjpCrUL3jCn/5kKcQinlJ+niAAAAAXRSTlMAQObYZgAAAK1JREFUeNq10L0KgzAQB/DmDeIHtF0jRdd4"
        "SLjdPkGr0LFDfAAzhKx2cZVMvm0tXGxewCPLj/zv4O50WCU8AktY+46YFvm9S3ZfPpDr4clDazXJoe9aMitE2ehu"
        "H5DOyjR60Hy3qedePyT5LMw4317KUCCzZhRuDWY11MriCkCeXFWgt576mXCidGBxISvc4gAY5l+9h98LZgAr4AI8"
        "Nsj/ehlucR5fg37jYx1TX+DNKNYtoevGAAAAAElFTkSuQmCC"
    ),
    "rindo": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAG1BMVEX///8xMTH/9zEh"
        "rTFS3mM6c0p7czHWzhC9/6XCE9nbAAAAAXRSTlMAQObYZgAAAHhJREFUGNNjYKAZEETlMioJoMgKKaLIugQVoupO"
        "EkFRz1gm7IjCL2REsUA0ENU2F2e4dhBDpMPFECZliMY3BhokGuoM55sYCwK1ByP4Ji5A5aYCcL5HiytCO4TvguAz"
        "CLu4uLo4o/ANjY0RvmEEcgSRHS8oSLNIAACbLxMqZX125QAAAABJRU5ErkJggg=="
    ),
    "rowap": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAIVBMVEX///8xMTHe1oS1"
        "nEIprbU63uacezHOnDoQlJwpWmMxc3vmNcqMAAAAAXRSTlMAQObYZgAAAMtJREFUeNq1zrEOAUEQBuDbN9gVEXRW"
        "I8rTaCVzydl6J6EUCd5AjSNDKUeWTje5pyTMegExze6Xf2Z2kz+U0u/DmOiOet3Veq3FaR1BN5bRSa2b+VFj9u0/"
        "pHvvFjFNmle79+PKRNenAYEhj+tKRO/Qw0biAJAzThYj8Z2ouuBhsNKfdcfqditxx0PxHdCVsCt64kAZMmytuB2O"
        "nLkit9KvwrlfOAKS95LW3DIw0UOs0pSLB590tD0zafP9f61F9A6ljGrH2ThhJP65nh09OKOt+LFkAAAAAElFTkSu"
        "QmCC"
    ),
    "salac": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAG1BMVEX///8xMTExcyml"
        "1oTW97V7vXNKjErO3mvm93sibU4JAAAAAXRSTlMAQObYZgAAAK1JREFUeNqtz7ETgiAYBXBpaAY63cFkN8Ldk9wV"
        "P3e9pNamWvvP80rgcvZtP7438KItgtDqAa/u5b/T2YyE0qHD9HUfgjV52uHtvVel1bW/E2Jq3RUP55izq66CKUDa"
        "mZszAoBWygQ7GwUw9dAQtPgCkhM4V9j1WxDMGEW+PiqwcxLZLL9TprB2xG4Am0yd9bz1ay0XWZHl3iPnQoS5OypM"
        "TqMQRuKTx6+Co43yASF+ISFfZc/JAAAAAElFTkSuQmCC"
    ),
    "shuca": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAIVBMVEX///8xMTGt72Pe"
        "97VjvSHexRn/72MpYymljCH///9SjCFJwExPAAAAAXRSTlMAQObYZgAAAI1JREFUGNNjYKAVEBRA4TIqG6LynVSQ"
        "FTAKurg4IvGF1JcsQfAFBUuUykvgfMGw1HYnJZWFML1tmdNSS1xcYOYxps2cmRbu4gXji4L4EVUw5QxiaZnT0kIb"
        "4crb0oAgNBDulDA0fiiQm4rMByoIDW2E81tDQQDhG1EQNwLBZwRxBZE8J4HKBXpekFaxAAB3nyUl/7jt/AAAAABJ"
        "RU5ErkJggg=="
    ),
    "sitrus": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAHlBMVEX///8xMTFr1lpS"
        "hEr/72vmtUKMczrWtUrv1lqtczGIbhkpAAAAAXRSTlMAQObYZgAAAJNJREFUeNq1zrENwjAUBFB7AzuBUCMmACaI"
        "dJYzgD0ATVIjIU70kVKnQtmW3+Q7DJD71dOdZJvdYt0/6+uWvrpd3IZo63uxRUZ1LmzErVc3EZK30zVeSKA6JACd"
        "+iCOiLo/AgGxHx5rD+QETE/dI8txLr0sOq69HSGZiocxCL/6/xPJhfKeDvhZ6I2aPYUlXmJ2yQ/3HCWdbKPR7QAA"
        "AABJRU5ErkJggg=="
    ),
    "spelon": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAHlBMVEX///+EQjoxMTH/"
        "xXPOWlL3e3P/5pytWkr/va3ma2O+/hteAAAAAXRSTlMAQObYZgAAAJ5JREFUGNNjYKAGYFRA5TMZoUoLO6HwlV1d"
        "hJSQpE0iWo2TEHwh146p4QgTmZJNO5NdkGxQd400KSlCsk0ltLwE2QZ1l8iZLkJICkI8Z4YCrYSZwaToEmYSaZwC"
        "N5PJZLJLx1SEEUwl4SUdLQJI/FBjjxAkJ6h4mrm6I/GVXdxckF0gFu6CzGc0dSovd0XyUrqCkFIxEh8UGkIKDNQH"
        "AK+eHhUEZi5gAAAAAElFTkSuQmCC"
    ),
    "starf": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAJFBMVEX///8xMTGl5mt7"
        "vUK975xSlDrvWkLW/8VCayljlNberTrv3kL7Kd4tAAAAAXRSTlMAQObYZgAAAJ9JREFUGNNjYKAdEETlMhqi8oVQ"
        "+IyCyqoCSDwhJSQ+o5CSi4sRgg/iOqvD+YxGQK55uSmML2qk4mJUXh4M44sFuTiXlxch+KFA1eWqxlA+h1hqsDpQ"
        "GqZfuC1j92alUGOo+xhnzujevTQ02DgQql1iVuuK1mBjY7j13YsjgFy49Ry7hZRbjeHKGRh3CSq3hgYifLOQQUJQ"
        "EMmzArSLAwD5OCI8hjlSBwAAAABJRU5ErkJggg=="
    ),
    "tamato": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAHlBMVEX///8xMTH/lDGE"
        "OjExY1Jz3lIxpVLOSjHmczH/1jFHMYBAAAAAAXRSTlMAQObYZgAAAKtJREFUeNq10DEOgzAMBdDmBnFUoLMzQEfS"
        "oSfoAZDgAEi0e8jgHQaYWSpuW1rZQOeqf3vKl6348KdopXcCVcSwUdlj8Yj05jQqm/vO7eJqNRiMmlspVv48xVDV"
        "HsTz00NtXMYNM89oE3S9+DwhpmhzHnDCT1LPTjpqFw+rAxJiFqQPAS0O5LzYYSAKndXcN/118TiyFdA7OWz/T4g8"
        "v3LlItNlqf823+/XvAB0wiSyuj3HSgAAAABJRU5ErkJggg=="
    ),
    "tanga": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAIVBMVEX///8xMTExjDE6"
        "rTpKe0L37zrFtSk6UjFCzkKM74ytpSFA07ywAAAAAXRSTlMAQObYZgAAALFJREFUeNq10bEKwjAQBuDkDXoVO3Tz"
        "OvQBLpCuUsHZIRXcXBScbAr2AbLkEdqxg/qaptAL+AC96b7jPzgSsV5BElsJIMCcIlNSYEzDgcDD0VyzxbJQtXev"
        "JJrqahx0dKrIj4OD2+KNJu+920+83s2mnk0dVd6RfS7WBc1lEzbOVMgu+xDAsuTz8sYiot3x+dnljthjy96+z4Ex"
        "LmTzDYSJLSANzD/w9x4ye/AGD1f4hB/R8iZCUmTs4gAAAABJRU5ErkJggg=="
    ),
    "wacan": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAG1BMVEX///8xMTH/9zHW"
        "zhCU94w6c0pS3ntCrWP///+3Ze6sAAAAAXRSTlMAQObYZgAAAI9JREFUeNq1z8sJwzAMBmBrAysO+O5M0IhsoHSB"
        "4vhcaNJzoY1WyNg1oZbb3vMfBB96gMxhAfx109k/nyoQDDTVMLbWAOlCe2ZE/DKzX2c13OU2LstFLTFxnB56LtLw"
        "5FQMLhBNnMq4C6GjNL8+hn7breNh92rVIe8nuRb3mYOg9inHS/3WESH4akDMRX1o3j80GeCsCM9IAAAAAElFTkSu"
        "QmCC"
    ),
    "watmel": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAIVBMVEX///8xMTGc1lpz"
        "rTH/xa2174SMxUr3rZT/3s5alDrelHuQofBqAAAAAXRSTlMAQObYZgAAAM9JREFUeNqt0L8KwjAQBvD2DYwKgmMC"
        "2fWKWkcbUNdKfYNG62YHQ3wA6SpCJaOL0jylgRz+m/223/FxBxf8J4SQL9JIkE9ma4DXIKRMrikft9AdmJwo5dc9"
        "uruoKoCROWNdVHwrRC2LljdU+UrMdI1us1PGBFU6vnnzPGVz5Xz2pilQY64aBt5DlnApC228O0mUSOdj493XYmlM"
        "HduLd6jKjVKX2ALefyh12L0d9ErFrbM75xeUG9sAmBs6bIq7s6tjiL1PDf4DB9aS33/+JU+nfz4TiaPfjgAAAABJ"
        "RU5ErkJggg=="
    ),
    "wepear": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAFVBMVEX///8xMTG192NK"
        "Y0qU3kpapUpzxUonfR5QAAAAAXRSTlMAQObYZgAAAIhJREFUeNqtz8ENwjAMQNFkA1tVGMBKB0CFARqZ3qvW3EGQ"
        "/UegbhUHhNRT/+3ZF9sdGP7SE+zYY9N/M/BlrMRTameoJE5RHsZEzHEo9jNRZM7F4anOeSxO2x42emEiXjIr/n0z"
        "v1b3rviuHOzcIML8FnMja2C+Kidz6HRwrr9LJxOCs3DJHdMHLE4g7c0K7PkAAAAASUVORK5CYII="
    ),
    "wiki": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAHlBMVEX///8xMTGUc+Y6"
        "QntjWq3Opf9CnEJa1lJKY0KEWs7VDCU8AAAAAXRSTlMAQObYZgAAAKtJREFUeNqtkDESgkAMReUGLOABzIaC0t1V"
        "a8i3sMXZE3gHLmDjATywMGZBxpbMpHhJ5iWT3UZh8hVmdFhzEPNDpiDrl8Ke63gejrOi4Bgvr8esqK5rLuoY78OT"
        "87SMEMm7hbnviOitXBLTxKJcgTBi41rt9464axASk6OThW/zr876GzkrfFS9AJAgSPeWgMeYiTMIB2Cy6UJBwGRL"
        "A5WHqE0fYkL799At4gNPjB7UTD0ISgAAAABJRU5ErkJggg=="
    ),
    "yache": (
        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeBAMAAADJHrORAAAAA3NCSVQFBQUYJt5DAAAAHlBMVEX///8xMTEh3lI6"
        "rVopWjF73uYhpcUZhK1Cxd7F9/+/4xWpAAAAAXRSTlMAQObYZgAAAJxJREFUeNq10DEOwjAMBdDmBvWAutMToPYE"
        "pVdwVMYO/GRlqU9ACAfo0NsSIeKoAxPC25O//+DqX0N7mpbqvYfTdxuivu1J2cCN7XDMDYfIVsau+9jwc2WRM+X1"
        "dNms4FaV+BZ8mHMb4p0RH07PpxiSRc0B8MUpfWXr1IhgZqf9zZI8YVYLAEGdbcSn9hQvB/HdpoEFQrvnkfLHeQEl"
        "ty0Ruo6ZYQAAAABJRU5ErkJggg=="
    ),
}


# Trainer portraits (80x80 PNG, base64) from the Elite Four guide data.
TRAINER_PNG = {
    "aaron": "iVBORw0KGgoAAAANSUhEUgAAAFAAAABQCAMAAAC5zwKfAAAALVBMVEX///8AAADunErFezFSUlL/1b2k1YNii0GUUjnepHs5OTl7Slq9e2L////F9pwon3OsAAAAAXRSTlMAQObYZgAAAhBJREFUeNrl0QeCpDAMRFFKMlgOcP/jrmzPdM7U5j+h85PVTO8U40TMuQVUb6F6ke0tke4tiJELNhMkb3AtinjkPLC8QW4bA9zi1smttYBxQbbtG1w4YP9NY+u4V0R00q2amkoBF6tuJrPIAivqUg1rB93bLa5INc0DjAxw/irFRPBcnL/7CES+IVbX0pwQ8dFxLklYMkvzXHHDy3gqppQzLsR2wpucv/BQHOv5aUoBSjk+Dbv2kHNKTz0H2++oeE3zqqE1ZoxxfXJ9KKLO1WcWAB1MnpvNq7UdaMxwajSG4/HCX6vBS6OQv7zsI3pdA1AwJz/DI7FxoyMaQs6WPaSv4H3P7Uu/USkOBsvB2VRq3x/XZ3iLdEs6WHw5QsUGaCwQEoJ7ojlhYgSVkE000MCgIu75OScSGNQ9DzQwS+CCQYne5JSIUEExJ2kg3MuOKgs0seBgUFWOmDV00G//TLDkYxxw1dXr/8Hw1GueqgQKKCIqJi0+KGCBmQuKZnTRwPFEFawvcUCCCXywZSQQ0zcIGjiBCCqONBs0htdA1s4DxPF+YINCBP2B7d4ZdgnqblAPBtREbR84EBwf8EFV7ATlFNQ/EJQOHh/tFCGeCk75/wEUpYFQszNQzcGAHaCqnV9ls72gdwqq2scgsIZwBppz9jGI1XMSOD5noT1je/YFroZ8Ck4wA24OmXihNf3KfgBmhBYe/+AgFQAAAABJRU5ErkJggg==",
    "agatha": "iVBORw0KGgoAAAANSUhEUgAAAFAAAABQCAMAAAC5zwKfAAAAMFBMVEUBAADguJi4wIiYoJi4kHjQaICgSFhwQFBwWFBYUECIeFjIyNjg4Ljw4Mj4+PgAAABCfB/7AAAAAXRSTlMAQObYZgAAAeNJREFUeNrt1oEK4jAMxnHbtU2Tun7v/7b3dfNk6AHQFBBuf0UdsB+ZkeHj7j/r7s5Gi6wYo1l8Ml0z26DosagrPFrvbAF4eH/RrgvA/gZ77+b3iCjXoto7xae6N9KfkaKaWV+xF6NhYWfRzkVH9e440mMhxOF5QYqx1gOsdoDmBJVgr3tI6MnMP+AQ6552intY4hE8lhLYEpBLNo4YQqI3Uv+AFEMqJZhFW3HJyr1WToj6UOCxJNmwzGIi2Fqtm2CRVzJ6a22juIIsOZcspTfbpBQsAfNA9Ym8ABRaB5g1goPKCq8wvqFk5zWLnJQA5cwFSs1HIPECMcxZsdZdhJ4MG3KCwjDp7WFPQwS9rZ2gYNojmAZYTq+3JqxtmAcBqAYZXu+NzyPF9EqgbMyXCZJ7kToLqqmaESwH+OIYZkVcBxz5RmTDew94MeECJV9B5gGv3+AFVA/4PSDDL4HlX6DOg5I/QNdPUdN6sHyA7Uxc4EVsrwqmweuIbTxG4gFHQ6RziC7QtJzJRuYtSnGDJOXlbSJlGlSVciHP+An0Jid8ACdydVOdvn0pX2tKqeIdD+dBG+CnwGO47tj1cyI3+AFgLNkBfv0lhIh4QPk6H5gdEQSRc/46HZgDFcqT2ePu7u7n+wMyuSf0xw/LugAAAABJRU5ErkJggg==",
    "alder": "iVBORw0KGgoAAAANSUhEUgAAAFAAAABQCAMAAAC5zwKfAAAAMFBMVEUAAAAQEBA4OEBwMCCYMDCgSDCIWEDISEjAiFjogFjwwICwwIiYoKiAgGDg8LD4+Pi/N0t/AAAAAXRSTlMAQObYZgAAA6lJREFUeNpiGDRgFIyCUTAKAK3WiXarMAwE0I5khLBZ/v9v30jmhXQHmmmb3TcjjuF0eLU3qb4Y5M+rwQmv83SK6KvBrKh/lFRDALWSFfWvg/PQDZrgSBHRFS84eGTLSFHf+Gy4N2ne92EDIRgi5VsVlYQyh3iA0fN6kkk1rFICZPKeM98Xaea0JT2C8XgXh2G46BUm0dS6mGqIw8VTB9qhY9wD7b2veUF2Mc1HuS6STHTQe2KHNP/Si+9Qeri4EaFPYuVfuv2VSx5DSrkGu1hqqZVgHdXzwKZ3ed5YhKlQ0BrR+PVyzHtHHKBRqD6ye8D10zk81QJUdUjnTJQgvVtnM70SIVgBS8/BgrjuIb1sGBV9k82kOjYDUN5ueIl1EgK4R0E3d4jcKciQY0QmYVAzdIW5DjLauXVtEwI0z4a47yXHpAj3edvSA/9ugJ1bAlRVMub8IYahSVsukyJhpahj2VSyGgwytKaqTa6RS3AJ0ptSNDgcQlC3Muq6Potmv3iJdVHGkSAEzrDgKttGUZ5Fr3bWI1gIzphChEzTDmI9RFXYWY8zS9FZ1kYxQDLzDqpq96ZxhH1Pygdwlb4bRdILkYBIHFwNL66Phm+nlvYRJLF2MUAGAItHz1EWxC6w2Pd2ysuny3swX0FMXoA3lK06xYovvTHyEVTVLk4PjyBTsBCag6P3JTgx3exe+7+1n8EmaxcxUqqw+p2HRZnDJChNcmvLR7ABGNW8Roze12DkYXaw70R5VGwtwLau46TueY1M7nsR7mGSbB0sRR9gePwegt0LTn68tCbIBFlytYTXWgcbI41iB811WQj+TJrHkREdS18tEkSCjVkSpEeO3m8gSSNnJkuK0tGPYMuCihMexVpZ8Ttwaf/B4E6AjFF0W0LMPqpKYhAZ3oHEToKoeRBFRorS8j+5Doa3g9JzwiPoUdGri3DovGjPmt4DFFnneWOAEyBn7j/iFPednWBSS3BrcpEToszWQVTZFoI6BzikltezqHcelI0xYLNNdQuR3rpGxTUiB8fMFM+Ae+Y5RBE6sW2617nTFbEdC9zN8tw9QFl9uwoeIskaIrOLZhY74HmGE+CzVytLZghS65kfHAueB+fwOgk0lvPd8/MTMzIfI3fBRVAFzB0vKgZ5iI4AIcxu+k4K0js7tJkztR6e5EPG7LSWIiBRcwbCDMUO0AC+dWinUeGqxI+GEUoEO3fZzHWJGhKLv3jhlve8EHUHT1AnZQ8vuVeJp7V/z8tJn7row0oAAAAASUVORK5CYII=",
    "bertha": "iVBORw0KGgoAAAANSUhEUgAAAFAAAABQCAMAAAC5zwKfAAAALVBMVEX///+9vcX///85OTkAAABSUlKDg4v/1b1iSlqUYim0g1LepHu9e2K9QUruxYPUkmFPAAAAAXRSTlMAQObYZgAAAc1JREFUeNrt0gey2zAMhGFC2oVgk879j5sVLD+lTLPA9Pzu7Rtw4Pa///3vf79PvjfTsz1m8zy3jJPAM87wSMv7WaBTF6M/RRQ9IdzFvJsEet+yTpsgQuB2tINeHhHu/QB99xytLK5DWh/jE41lT60LBA4sw+lOsrpkbuPYiiuacdJSOpMreUrK2LqO3HdQfN0jeo+hS9B3sioy7ojeO3C/R+6kWtwlRYy7ilYPAtUtEgSqHMxC3O0Wt2QX1LxlcYubQt5XQXkCLbB3gAtKnsDF7AXKq4C+PEEZykLlWyh4ZkmsylIvgG5KxCzQlywJT9CY/jXQXx5sP3bE42F0Xh7x4NRz0Q9VAw/R4AmGMqNdBdk7pZmh+TnhogReEGPbJKZ3gMCKy6A8gUED9CKZlbqs59bt3Qn72IL42I6v8k7QFN4H0U7wOaHR9hd2AZR3/n/Mjgnp/ADZ3hOf3jlhlqA5d8/ZruV2gkZTeIK4DKoXmMFNEVVPvdZBU/PA48xtItjI0SMmgi22IfIyiO9AiYUJ/XuwkCO5r9dc6vQyAG0qKG42OFdEqweSeD2bDU4RcSr4D1a9uvhHgJBBzAOxKkwHv35VFFWrgG/wf2qfAQvFE8JIxe04AAAAAElFTkSuQmCC",
    "bruno": "iVBORw0KGgoAAAANSUhEUgAAAFAAAABQCAMAAAC5zwKfAAAAMFBMVEUBAAAAAAANDR8ZGSUlLEIzM0JiM0JzHyWpYkrYO0LPjWKpqbLFxdj2xan///9qanMfp0zVAAAAAXRSTlMAQObYZgAAAydJREFUeNrt1OFymzAQReGshDabBcz7v22vLpKBCXJQzJ/O5HQagNZfVwL346+/bi/EGG8WhwFkRm+BIxpADjCHO9Y7PMPpnRzDtDdyFN8cMHeXR5He3ozoLQ/Yir4zpKJ8jCXN6BuczUir53H2yH4pKjSb3cqScTkQDDpz/SF0ggLQjSMGCA5wyFSYjYdOjqA5UMvnUXUepoeHClLsBZkaRsSHTadEMNrvJ6SXQe6o+8zR4L0BmgZeBV4NpDwQ7M4I+h40WMFcY/z87OXqY4bHgs1MZ3WPX59fsR9kFVRT5VMnCK8XlJDWRMqI7mXZzk0cIFrushdYSkHqF9vM3JwgvCG/QMjtGvgsSf1iI5gEB/5yXGVSO0CcCLx56znhMMR6Sy+BXF4263g1gND24CWx7ldQHI9iiJvodS9+FJ2p1XW+BEleAQ+bt5lPMPK/uEr+7NnGNdbs2344xZeg+cy8BcZccKsLsDap4EwbXgHjsHqIL6S/WLa4+TfKrJ45xch8bS6gNsFvD9eee+oE41ooHkU3eQVuiagBRDzEXSJaxZfg0eNTopgPAZXpYgY0o5zctP1QtvdOhXcIPqMW6pdO1qdiJi1QMkdSpN7ZRyx4Bpkaw4StlJsiIocnvxV4UcEgBRRpioL0eIdGbQ+GEIypJIrtrolBiigJYEf6AhR6naD4mUiQwQu3gFVMocNbkPiZKMsCkSQOl70HEj9LpyklM8lZcxz0TYTXEieIakhb46Bxj+L8DOSyJXsptcEF/yLJaaqTLryxc2wD04TwGZDnXhrHEX8FP59qHhCnyY8kwfR4LCirSVXPwAkVs4YBKYI8llK+PWVv5Eaeepjt0FQ8kgcNHEqPLGKEdOJJ3cCDSG/kupdUy1dcLtgRHsCPa2D9HIjleHfleZrBSS6DLAHNIn+vPzJYtqUXZFxnVgGBJFdqT0ixWbEgkRwfb4OHXTyC8E5KBLtrg4L3uMfZwHOPiyY5TV0gX8OWWMgecKTXEtNUGi+D9NoJ46RXwaPXZtOIXj5b/jm9ayW0tLwJYC5JG7iujiMpRK6/VNnKJVLvJlsff/13/QOjtmhz3UZz3QAAAABJRU5ErkJggg==",
    "caitlin": "iVBORw0KGgoAAAANSUhEUgAAAFAAAABQCAMAAAC5zwKfAAAAMFBMVEUAAADAgFj4+PjQuLjgoHDo4OAgGCDoeHh4UDB4UGCYaGjYoHj40LioSGC4eGAoiICfx3fQAAAAAXRSTlMAQObYZgAAA/5JREFUeNpiGAWAXupAyVEQCALoAtIygN7//+0NjZNMbk1dbrWua5Xgpl71xJj/lfrMPVqMMY+klKrINY6aQvFISvkSObnoklNO8nMvZwWeWOY+48cgCLhcAZl6BnLi2ypeK0gx3VfwZOjEflcCqSEl41KtAde8JSxLCEX/2jiNDS56KqpTWmtj0e2n4npyrahGUD2KZelhKZ95J6L26aH3Jfzqe+vtVw5L79oTH4HrCch2KiL23huyYpz/kwlPCxLUhNaHuIMgxfeFPHQCEhB6rYFbTSnfRS+/9ygE0Ya7eqUQPCct7z2CLFmwa0MJAXphkuE9+d4b1PCCSk2gi2okKdYpckw7vdMIBc5HT6Q1EVYcOUSYF+PK01vOhgpjYATJeW9tz1mE4GQrn0KhF9fVwFUzFzfs9AaoAX9vqoJpkPofB0oHwUh1QCnGxL5p9V54eCVHginWmjUyvaCegruByUBueOZ+gIOhOkREek2XmKS1ISJojoKyCxEFk3mTN5GYeQWRoDrjTZJyG3cHE/waoIgp6xlYymIJAQiZYJu/1kkkzwgQKr4wHsfJpKMPqRwP8MkFhl5MLVeCkhJI0lQUfUcH70SiR5v69KrXzIuq1bFESRoTifbWO8ikpCBFJRO51W7wM/RSTRnDqwRdyapcl8mYRzIpN/ZwnBXMScE0wYzEKExQWm9yKC9PdiA3wHDuKZhUHBJDeH6MZpTlKZbwfHWkFILDU5CHkinDRNIC/1vi7MVEmBfMm5jk7EFNxWBDKfb0vwEX8wiap2Caz4I8wFAGyGHI+YkXFQcZ+IqgeRMUajXythgYis2zMPDghBbmAdIzsDqQKcFleIXjo1D0CRTN45DUJiunYCjcQsFQAJTgPAPTs+D44otkEfcp1vAtcLfVzUvQD5wkavKIrm5mwHNFPSf6EEwzIpxY8w0sA3nOPDSKOPMIMrtIZKb354cIP7CR5QWD7j3YPUjRgwcLir6iFT2Wml5BipHB6005KMC8yRV7jgEPUiTIePAxFikfHFesNsorKPEErObZqKc55BIovgfJfQAaG5haaRLMzsso5D723Nsr48Ecc4bXPi3oIy9efAELxY+88h3c6GVx5YC/iiDmwXqAm+QR88qUgL+DgPNYcYLr9idY3HfjvQiirqQcngPLs+InQRgoDJXDoyi8VsDjYxBHUTaFTI/iAAnhOP4pJZQBS9zoURSDoMc/etZADo4RfBH6WcCzeYx8XQxBH1z2ZK11fRzbHaAy2+MgeFG8c2IGsH647jECyA5qN4H7Lq2120Ao+KWi3AZuCqL3u0C0su2i4H4bqCLW7TYRTUVs69572+4Ri4rLdtcXm6SmbSMG3qXS+4/5DQ+WM2QYjRayAAAAAElFTkSuQmCC",
    "cynthia": "iVBORw0KGgoAAAANSUhEUgAAAFAAAABQCAMAAAC5zwKfAAAAKlBMVEUBAAAAAAA4ODhQUFC4mFjowIDw4Lh4SFjYoHj40Li4eGCAgIi4uMD4+PhjhO0pAAAAAXRSTlMAQObYZgAAAqJJREFUeNrF1omSozAMhOH8bRkBmX3/110hmAT2xvbWdO7rqxaHK4+vjG0ZyU1bzEd5U532+GBvjBjj5sR1HGjzNFC0GmDdOEuQEQWXsPJarapTJMGoWAOstcCTLk9WitbFkrOqgvWISKr6xjpPNUFMqA+k+uzzkpzV8iz0jYzZOs/zsliCKqV3N3sNcYlYkoTXDfo8e9RkG5sBJ3KK4eG5W3ow28AQwVccusGaC2GlAIVC9T7Qpy3BUvDtVr1WrEeMRoFku4ksbLLOPRylDMdt8rgF3wM+dk6xj+W2rWFG7RKRO8WXhRKiGdgd0H/kUARtXpEAmd0QfTmJYufEU7PKFsWNG6D7vLg/yCQhCQKUnvmKW6Avs6/LDEWUPZCbkWeigkDviD6vIfohktwBSklxB4yGa8RDRIe2gx8fJ1C8QPt7Q4iW1zXejQBLeteKfxdh6wniCj6f7Pv3VXFK0aYU/4py9QwoCe5iKdRtyTCbArydN6hDLClm2sDXUclR8A2aNRaEkk5wKOVad68PFIhCeOa1mrVPvIPyRZtolmLjPzvnJbIsIebAcXVv8h4gncDFsQNsXmFz2cqZWZfVZ+8SoaR2iPM6r32g0AkswsNLsQ1EhKIE92CfYJNIOkppBIjYlXPFUeBVTLDZ+wlMzxpAzuCnLt4FG0FdQVETbPTeFIcndq8HVIIcoLDweiZGr6JqB9EfwPCaQb1B0ovQBr4KHjKoB5R25legaCm4g6SoUhgABqMz2CUmJAmlWKRBoA5pDMgFFKhZBJHOWeLcmZugziJvRoiSl3ugdvEnsLwuTQ0fcAXTammY4uG+Rd4i6TWEC/igT0uQM9gfRHoMAkMcDor/B44SleZIkJFgiIwF2UGNHRnBwIaBliJEgsPG/jv3HYACGG3Ty2KdAAAAAElFTkSuQmCC",
    "drake": "iVBORw0KGgoAAAANSUhEUgAAAFAAAABQCAMAAAC5zwKfAAAALVBMVEUBAAAAAAA1RU5hNkBmYHaIg6A0MDX4yGrVqZCYeGizklbGxtX+/v5JdKdvgPZSAkn2AAAAAXRSTlMAQObYZgAAAmFJREFUeNrt2IFq4zAQhOHMaL1ryXHe/3FvJKWEXAI0kgDuyA8uYNDHrqsC9PLt278R1ELOtuv1eqwTxbWw0juOY9WM1jxEOg5bNqAhGHYcWOEd1UMKYAUoT5ui1LBiZZOHKO6kO9Z4XmhmDoBYASY4CWRcMe9JRN4T9GPPOfOyoLTvSdx+5E3eGjFLrH8qi0AAWVdx2yRigcfzBK7XlNOx3W7zJG+3E9mOrGc7b7cbMOt1ETjtPM8cEZjxonZKzDxrgbkJ4bVSwZxYvctcMCqJzIoFPieCvIsV3FOsAL2CkXYlELMbG90iTGCtcBJ0IxmkxFxBFJ8SwQoiTGTOe84p+5ToJgoQxzZhBqZEsHoXRFgFFVITMTygewWpfsAmOoZMJ43PYE4SS/ZufqqCIh2CVdk7qCgys/cRCqeZeXMLpfWdG4miIkpHfy2aYgOD1upgN2sV/T2J7tWC0FFzpOfuaPxSdItoYKEBCPMXUX3w2xEB6wNan/AFlPVBMAetg0bS1LP46cWJ7pVG0WxehJgncNswvLACHxNWcathdDzlTxuzefYD+uceyL6xRADS+tLDEzp5H5BCIK2am985jAx4B9GErSaUI+MpgC4PZk3oYB8REDggEiQedw9+H1HYgKewERL4A/IBDqWB0G+eRDy+onEY7KF9Mj3g1sMYeD9e50F/5kB/PT23M+0FbO9MDQ1oVkVNsxLUg2ewvxsCCbyepSkfvNaE0L9fwn3Uc7w7Cqf76IDGNyDNiSHP4Xj73n0QdL4FSXcOeDR7u7KTIxcH3no3InxoabQG/lP33/bt2x/3JBcYGZDEzwAAAABJRU5ErkJggg==",
    "flint": "iVBORw0KGgoAAAANSUhEUgAAAFAAAABQCAMAAAC5zwKfAAAALVBMVEX///8AAAAxMTFKSlp7Slq9QUrmUlqDg4ukg1q9e2LFrErepHv/1VL/1b3///8Bqtt7AAAAAXRSTlMAQObYZgAAAk5JREFUeNpiwAlGAaD5OlCRFYahAGpu4mzb2Pn/z31JpWuHeQAkBfYuIzbgMbEC7nme/tvHvV6v8Tu3cTPnBs+Ux8uLDzbNvwbKKu7Yl8lo7103PEVxo99RNTgpGmjpd0RuL9miCdacc29VF5OgXS9CBiq9VU6LJHfZhDf1kQkmRalm3aBK3nPy1yOZXFZUB6vSsSdkWK26zTOxjgdItMszyjxpjfZ4XAoxEW0DLy5EN0i7wKrKja+ygSxkDKtqGeB1IeldzcGifF12buCFNGhhLXa0BrOgMTfo3n3eSgZEc8TFCbbWkPFae3rz7toG0K0ZB0sJiygGYAUvtKIaB1WtGyxe85pK2LN8gpjFMIjjE5zVqPcJtjbAWiUG1mreA843RrRXhMB+X4h2Y79g7z0IAnBvia/No9jIP8ygB7wGCHCNgWQcFvDyPwPZ7nOEQFRVEEopj3gAykxHLGBmgn/CipQ7XtIoSPwDmLV8DhNsYvOi4OgOwERFTklMfJwDGYOzHwW+1qxnuUHLEDOekCsADdYiQXF6Ds6JRyBRUKa3gpmhZfEYD8gUE+U8JwhsAm9viLSCYi94SFxA0ANy9H8L9x6QaGkxBh4PAVqXJO6lQPdWUHZ4q2iLDIg94OqtpTQI3gVivTwtTtAO9HUPxEDGN4hRA1It0lqaoX0tZkH+Lxj+ElnA6c2e4+DTD6U8F+eepgeeAH+DCZF49faAwApOkcIjU631ox2qzkVFIrbUuoLMqtCqEZG0dvT++ZKAiD0U3hMifDUe3pT449+YfyIDIQacRNnEAAAAAElFTkSuQmCC",
    "gary": "iVBORw0KGgoAAAANSUhEUgAAAFAAAABQCAMAAAC5zwKfAAAAMFBMVEUBAABqampiM0IzQkoZJSw7GQdqQg2fQhmpYizFaiWpYkrPjWKysrL2xan///8AAACdaptYAAAAAXRSTlMAQObYZgAAAg1JREFUeNrd1lm62yAQRGEMdCODUO1/tykhJTh5FJXpHo1P/9d9R4evUylaq7xF4LCM19slHjFaZm+C7oUtgjZAXlfrc/rb35/Z8oBM6AX87JWiAk1DmpVCg6dNc0FEYRfmb+t8+llYEwkS26x3O98DWxS5dgd6682Kr4ogx6Pj8D7AZdHIcdt69N4dBba8c7Pm/arCw3JorfW75kGQtRZpDVAiRo+xEqu1NQg8FBaN84m8GGMp1mJtjiAJJaVXrEBQlfZ9T1Xngd4QoQK5MUXeofIYyVeCxMs53+SRVAMi3eQcMcb4eMCUzgts7hxLKc9E4CQxppxi3Es5nonkcF5j7QkexzlifeSNhsn7jwmPI8bW40MQAxzPU8w51Rh77Q3PQAD3HSyz2liteDrgx+YppZxQTy4iPAMRfgVzjhGDE4EpD+2ZB5zga7/KuAqPwdskeLAd638YRhhtWP4DhpsELwU4SFyet/lBTmF6s+3Mg4h0DM5F4HZ7sglJSUGKN+gi0OwCZSOaiXc2hxQ0l4PsEt1VHrYrqECXg5CB5iP47wFdBjo2jWgXiAAXg6IvItwuTwXaBDcFCHcbngqkNjwVCL/BKbpgwE/QN+jB5Y3vLX3+jVV8CScI0cYUh7e2s32CGKBg5wxgggxrHjLDB+hrIL0Bzh/tnICHJr43fxKd3hmCIoDeFYKmOfIf7Bt7jykg7L3z7QAAAABJRU5ErkJggg==",
    "glacia": "iVBORw0KGgoAAAANSUhEUgAAAFAAAABQCAMAAAC5zwKfAAAAPFBMVEUBAAB4SFgAAAC4uNDIvd3ltJGllMT////owIC/gGl4UGD+3svw4LgoYHDHx9lIkKjTy+O4mFjEGAzYoHg+E2SZAAAAAXRSTlMAQObYZgAAAjtJREFUeF7V1tmK3DAYhFFXafPWyyTv/64pWY7AZGYILhHIB92Xh/rbBnr6yz7UNCxxuxpHimt9jFknb5yodfM8GNxFDhPlXfKfDK6cPxLntUCnMZliJYG04Dh4nu+B/aeCiBlLSgmVu+epeW8kZrX8TGnbNmC+D+J8oNq0Lml9LBLTst71FBq570zqVZZtwUo4TwSAyJ3bqnUqPTYKIC1TN5LL1sTD+/HjLglxeyVnpsOrIMWFgnvjdnFyP7Cs27aubSBDKAF3F54408q6T6GQEicvICXIO8VS6HkMAfJaZDFBMlFkABteSoDFBaRlIVm/BGqe4yHGXIDztUlAKFI9UKLIKkI8CiyQUYUcnlDPgBEgRD5LCaWUpw9WDcfVWWaOEIsBYAzVE+6CzLGJqsjLCCPAxh5epgnGNjFXMucGBkNEA5lbghmCB54iQDKDJBBIH6zrClnfR7LQmChSIUss0kBaJysyx6woSmIAAh0Poo5kQuY00fXy+VGcIM70rqAZYozdUzBF5Kg6qDjAy+938/yJiCf47mDmgIEqx8tEe6Dk60R/YLxO9Af6E7vXQDUMlHcBQX/gVaQ/0Ae7909A0PXsieNBxNHg1bN/RMTvwWyC9s3d+x9AeT6I+BWYf4ugfXH3Wg74qcgbF+NLzwf9hdeLe9ZCHCA+B2GB/nuIC+hd3MkGZvfiHgYO7CTGggqKf3jev3Y+eHSCrE1GfIXwqkJj8XiE8DBEhuqhA2AVX/dFKE4CeyTU98AvgKMs5JkumEMAAAAASUVORK5CYII=",
    "grimsley": "iVBORw0KGgoAAAANSUhEUgAAAFAAAABQCAMAAAC5zwKfAAAAMFBMVEUAAAA4WHAgICAwOEDo2HDASFComGj46NhwOECYeFjQqIBwSED4+PjosLiIiJBAoMBB1F+CAAAAAXRSTlMAQObYZgAAAk9JREFUeNpiGDgAaK0usByGYSAMRzM1F+5/27XsxIW3jyxpofz1D9MDAT9AeIDCN0gXUIYDHcJHFAKiA8AHFMo1VhI8OEUnEiSmQy7UR2RK6CTs4EpLqYJdJA6rCA0cUwlO0LzQTGWKDoFEUvCFWpPYA5VMtYNybymZPSUJJKYxop59CEqdYG2Hz6ClsVXgw8V4izGl6tUXbzoxOvbpKOnUF28Ao7owOK3p3wBBEYb7E3gC+2Bq+tdBiCgY8vOZs6GxpFY6mDMpOiHf7/tga62UWkrKvUyuxPt2ou7GtXYxtaAiBYSKCm4W1jkKBiHIMxHba1C5lKqCUO9MxLYHlNSnKXioKDCAYw9Eq6m2oAZIkS7qIhtPMg2DgIICoxdvSDhpkU7yZgUj4gWqxwib16csT0EcXiDFFYSIL0jluuoAxhUIQhOtYPkACfsyT5DTI+EDQjhAWYl2UL2uEi4gz8A+9mUu1xJjgAInEDxBMYJzFUJAQuziBA8cUJBuoJpcifQClwjjNlneSvQA5VOEB6gibKB6CzzPrlOkK0hNtJ0OpzcZ+ILrYmC6ACgymWXTeA2dIL9jDWCWAcIETm+BZ+ASsenNVRhUzJeBvCGqV+IVOMCwwPEQG6eZOAIVDCL5B8zYP5AVvId8LFDFLVC9Cd7vZ+BaBWEDXJ/v4GMCa5nvvmDI/uDDBn4H5fkNFvD74+hPWJYZCI98OIKtFBw/YDCAqLXgR8zEvkcUEPiNbvtgH/yQrVZgHwR1PgFUcF/EAQBfHgFM0mfAM9tPnNn/e3+XfBRBCwjWRQAAAABJRU5ErkJggg==",
    "karen": "iVBORw0KGgoAAAANSUhEUgAAAFAAAABQCAMAAAC5zwKfAAAAMFBMVEUBAAAAAABSLDs7QlosLGpKapaEhISpYkqWahOWHzPPjWLiuzP2xanFz9iEn9j///9Nbou/AAAAAXRSTlMAQObYZgAAAnJJREFUeNrF1ocS3CAMBFCvQEAE+P7/byN0xdfSJM9krxferDvb/wgzn+rlfd+ZDzfuWTKbe5J3hM/qp9QhxsHMvDPnA4x7nNftPFDGkHhF8wwcFuEwiCvI+VyQeWZWMMfBfAVxEfUw4+BVZOU0fKnrYw6CvEQDq8RB7E+gCLEtcRxU8QeJVJxU0Couj4OgeneQRMg8A8OegpWI2b7AOaDIExj3mmjsA++M4BYxsN5A1nhF8AJNkaZevYI5ADLvtMwGiOZqZ46IpAyn1BMA5U0ktwj1NEi9q5huYGvkrnj10PoSu3naUCjmMdo1Bl5Fp6dgzcxXMaU9DMoYlVeQkpJsuxFIvCLVMQYZ2CxQMIPGqN6Kb2BD3nNeX26+4F6R2kOkoQGcYK4GolGjoY8bCHaDJgJjLEfNCvMUdIsLWNqQMcyt6kVEJTCeQaIQSAYeESEhcoNEQiKYs1y5OesS4QaxPKqllGkphUgkAKoo1GnOVixtTgp5KqL1NtdDS9pbAgfA1t9Ae/J7KmIacoCzhcANU7PQYi+azMwIgsoBSzRQxewX01XBg0ZmJeH3Lsakg856Uy8Gqnc03IwLg8fCh1IOcCsngGkamO4f4qB6b2AKecXA8gwWREH1jk8xEHa8vYEzRcFixE0MgdDRl0+wIABqyhOoeAlUBMoCj10PBkY2CzTzFdSCyQ3S0CQATz5SxRYCX8aTSBWEvIHtHXSL9OGZ6Afrl7kqguDnBiA/SF8n0wiBFWeC9ftsn7xgOzbxe0U6Fxy+iq3/EhwuEL19B8kN9tawfd3KDb65ppKfXr/07gNxUfFjJJrGCX4fiZXNF+fInyemMjLRCvAaAAAAAElFTkSuQmCC",
    "koga": "iVBORw0KGgoAAAANSUhEUgAAAFAAAABQCAMAAAC5zwKfAAAAMFBMVEUBAAAAAAANDQ0ZGRkNJTM7H0osLDMlSlJiM0JiM4SfLEqpYkp8fITPjWL2xani4vZfM5WMAAAAAXRSTlMAQObYZgAAAr9JREFUeNrs1VnasjoQBGArLU0wg/vf7ekiSD6OeX6D4dJynl6rGW+//LLmjqvBIuIai3czxUt60rqvd8BFg8/zfOdty/DAxOYKYnTemuqNi6TmOvG4mC2G5Rwu6XinZ/d0h707k2tw88PiAfQ+jYvpzmHTuhx9GgVDvqeZJUM2OBH0g+Cc0tP2lZDD/EzQZOQYmFPKeHqukWCgpjBWEdnGDOZS9iLa8jzT/r0Pb6JQKyAefsuRezBNEjn//337dk70QvKPPTvqyW3xaIEh/xVFJD58zj6EFGCpZlHrK372LgYDQ4GE96rOxIfnygWBI/mX42fvoud4flqWaRGhp2Ki2jTgbSWlzTFAu+KiMRJVik6ciRbvZCPhDxqZ7ZM3zod1MxHZRZFNdKRvexX/wl4IGp73OQfzvC/iZMYKanRO7Ob4uy20DgjeQWQWpBpKRWEMdTEKQX6Jyh5Uow16swzMR3CtKHEfDti0o4BbqyErhh0kRpQV9W8bUPuY8t/JIrJ6OyhawbMxM+weXPFYkd6XMYwcQG2LGjgQKcvoD+gIDuZykKJ7eXJNw2VxxXSquMCTabFMk3OKSzwTSRIdxRjzxFCakwDjHjVhynJ0GPSU3pYVFAAjnglawQ3/lhSzlNnBWhb4hjt6lfvKJFc8bXoMzoGi1UMLdGdEJ063FK/u0Nszp1H1G1AIvhBqLzhGjTgBilRvOzMchlY1sRcE9Pl8ilSvBKisRrv0ek/zYjSRQau9c6Lom1gBNTDy0gAZwMXYW1AjCseh254YJqJAn0eQIodGc7dd1wfH7fN20QZvcfQY6QZVKQJNjeBJj7dqtcETXsfmKqe8yl3kkesApctblgk9x91pmgT4aC4LgM8gyFn046JZ0HUQRvGATyDKMb+jIlAKfgT5JaXYY35ehhQFJ088/w7W3H755b8NGwAA0ionmWYcxh8AAAAASUVORK5CYII=",
    "lance": "iVBORw0KGgoAAAANSUhEUgAAAFAAAABQCAMAAAC5zwKfAAAAMFBMVEUBAABSEyVqJUJiM0JaWlqWO1KpYkrPaizPjWL2xan///8fHywDGTsDDSUAAAAsBxPO0KtZAAAAAXRSTlMAQObYZgAAA2lJREFUeNpioDUYBYBu6WjZTRiGomiFiMDX6Pj//7bHcuJh2pAayFN3SOpmzEK+k0n4Ifxo/9z3HkLoIbQmrr8C0nvIJNPj8QUwlAfjont3wfYOsHZHmwLs8djThDtgP23rrkcwmvqAx57qoBjalNhjYkeiJhsChVpqNVHovQdVdUik1yNI8r2X1EbAiSOu1bLEUY/PbMkUAx54P6mUyP1YmsRkAt55id5IkMl+wP0rfnjkNQX3DvzoqcY7wrramlo8/dunan3gJy+ZagqQ6boGGCnwF4cMbtGPYCLYRNSeoilE9qC762I553oGPfaorWoJAXI7VkAI0iNYC4xtzBbuUDsWNZnpyitAzyGKWEIp9Lx+g2oFF2QGT3IIIqV1pWlVdK8AbF0VWkV4rl9se28jyPtwdGToSoCRyKwCDqgTLC+we1AE9TENzwzL5k4xjmi+oSAT7B4GLGpmFhyvvPDW3Aij0cDwAPhnaP83JEYzGaqIBqpy+cTJ/RoPQFbljClx4VQYFaPjsSR3NmS+LGXdnEwobj7zlQF6F8AMRg/w+p8Z8zx7gKUQPB3aQd1L8S1AV3eER/BKYKWGjbjPm3HA9p1QvFLzCHqddWaufgsUkcJ8cyzu1NwaWC6DIdYf3uL13UCRiyOWABkxVW9guQ5CouqxJUDFV0D2BAF6rNwCC3J2RDlAhtsgr/q6DYa4OfACIZfBIq342Rgi12+Bi7sb3NVxG1S037UvXFBsT7nuidHTJ+iuTxGXQSwLz8sR25F54R7ozumoVUzpsQAve1vLlXkL90HmgO/Acg3ceaUU7EXcPHGp4S7YPZQ9GCJuDVha2I1YrnjYD8ggOxHnQfifngiugN1zUOseQQaHO86J5eURhHulXuAUYpjjIJoHb6GDhd60+zOWMwMiw7snAaJ6XURGOTVgzkB49F9g9RoI5Aw5AUIzA5reRFBjIiDHFGdObBTZHizSPGkcN+DMiS3IDu4GlAIlR3MchOVcScg7kOLoiB3M7chHYEHlRkEgBjAzSAeZvDwgtgyK4B7PEaRXbyxPsCEYBFn3iJfgSruvkBRwfVb03VYAnahkaYsu4qR33PiIo16I7o5/g+4+CPrIs73uci6GR8RnLw9OyBAPn2d83DTHhEMgN9fwGcyxaQRkqI3s4ab/ud8PJU6QzqdgewAAAABJRU5ErkJggg==",
    "lorelei": "iVBORw0KGgoAAAANSUhEUgAAAFAAAABQCAMAAAC5zwKfAAAALVBMVEUBAAAAAABASFBYYHB4WFCwKDjgcFjIiHDoqFjgsJD42Mj4+PjIoPiYcMiQkKBcerBTAAAAAXRSTlMAQObYZgAAAfxJREFUeNrt1keC7CAQg2EEKmqEw/2P+wom52nD7vXfOfizlk737v3HmRmwkqu9ZaTV59aI9QV8WCKaPVjt9wfWSqwA+0RjDc5o02Ln5B0L1AzGWa+DFmBoISKeFyyUVxOfQKRJMZICDI8MbjprW+3iuYUY3nxta+a2nc20xEteq5pqtVWgqbWmqDKtAdlaNZdXHksm1gT1YPUwYgWYSBG0atE0WS2hgI5iFTZPBshcstwLTbDRzaL7m/dSB1U6eFGki8/c8IpaOQOE8CjyNk+Uk11rTSpnPluAOaMByaJacRNIkU0MLjwhwK4WUBTA8OqNE92d5OAEnGdWCQ+UU0hgvXliFxulDKSEElyG6NGAcCOYCDqdoY1QcgyUP4NdRLoxhPbcmFgAdz6fwpAmegITXhRyznsCX+P8wOgtOON1a4BY5O3hHaWXlnTsOcAcasYKr+z7no/jyHnfl4Hh7dEacVDxtAos+3rwmVwD6g0Ycdbztj+3GuwTpWlQ7Rh1UGrNpwf2+qxAWw+rwMgXgBzeW50LwSFqTvR3m1wuTYkuvZvESZAKwPnhC2EODG/ZRJfkfP/NDMgvjh4iJkB++nISxGKQ6VN+HfTvQF4E4Y4vd+drXv4ahK6Kubg7P38rlavgeZZPE0sEXL4q/ATm87wMJkSfd2cA6d69/6x/IdgXN1wkHmoAAAAASUVORK5CYII=",
    "lucian": "iVBORw0KGgoAAAANSUhEUgAAAFAAAABQCAMAAAC5zwKfAAAAKlBMVEX///9iIDkAAACcMVK9UnuDg8VaWpTepHsxMTG9tPb/1b17Slq9e2L///+wyHpoAAAAAXRSTlMAQObYZgAAAYZJREFUeNrl1FcW5CAQQ1GkogGn/W93RJkJ/2jy6xx8TzmWf6v25uM+byZS3Cuq5vEWmKLTO2ZjGzyOjx6ZA2ya6z5f8Z107K9xP7/t5m0wxXGerbUlGsAm8Oy9jQQNu1lQP+852xA49sH7eTTbczzd4601ng+5+2JLsc8E6kPZjW30V6TAUQxgG1e/rvS0xgaRjeyc8BjF0nUyK6YE3iIDPpH3JKtLvC72+z47JJpWuKv7dIFlMEUbyEFSIAIuEHgIRKCawHo8D+UFiyOyRq0BRLjWOEHF4gGnN8VqXGPl8gqxPBtYI3KNXR5jBhdIYoE0cQwfKA5G8CIy1yZk78tbILDFsSuAXODmlea6r67I8hVE3QKZnoQEIW4PvM5O8gWXtgdK01MClPQdNCRQhW4weawKAukDVbhB+MAl/jcgYQcV/z/QKbpBImPACxb+FDBgBAOh6AKxQOs6/6lg4QLDC+IvAOECC/8OkPHngynSuglhA8egD+SYHMsgwwOqH1xbTPhX9wWbDQ/ilFSTHwAAAABJRU5ErkJggg==",
    "marshal": "iVBORw0KGgoAAAANSUhEUgAAAFAAAABQCAMAAAC5zwKfAAAALVBMVEUAAADwoDi4eBiYaEB4UCBwUBhgQChAOCgwMDgQEBBYgIiAsKiw4Nj4+PgosLBRVWJGAAAAAXRSTlMAQObYZgAAA4tJREFUeNrt14liKycMheFKAsHRzPX7P26FIC6h4WbiSff+3pf5IuL9l//7v39QqgrgGzlqcfkmMrgQGd/oBcj4G4IQfXrf8l9UEdWnx7jtkXjqAaUwA7fIWpWSjJrHsAM3vPME8RATt2Xr4eId0N5GTPHU1iPAG96hJ4mKcOOK4gjxDig/QKrOnVqKfAOIpElE8eOHH7+BL4sBJhVP/RjuBZheEwvO2FpGSE+wvOQJzj7iE0x1gAmveElqjCgPVQ1P74J9RJXHI6F5kmrzUBJe8mSI0MbFgxNgSuVVUODgUcWLiwN08RVQY6SnOED3zCzhy2CbyMnq4gJaCy94XlKcboQ4vBpLfoLARVAenqWE08UJjDV7GJ4IroGutRx0sZ5VUnjmoMXDHI6KlIJLoImIJjMcdtbzNEmqGqu3w0qJGUtRVVHZi+p1T7UE2AZ0wo+0g9ZQpFa7R9srYecJiBpZxCvqGwV4HmY1PDOunAMsjMFtQYUImFndCzFApkq5sQ6efokCdK+wY7HTjeccoIBqfgNxmBMTeHLOh6UOslDbbQZUGv8RgZI2UB0Mwr0Q7WyZHRgg8U++oICoQUoAZXYxtQGb4I9CgPUIzi9jjBjp9iFxMPuOmB1MSToYpHnumnNnA4uD6Dm3Ce5k4gHGM9ZHm2pYePWYnX3KUXjJt7CzhriC9fIHKaDd6y8nB2pf5JA6Cx88xEupo+Nsl6xWBHFYc+AXnd6L+8ILEmGOoxrX3wKDDLBzr4LARKI2E9MVjy+KZo+HkxMYK39e9tvxRc6MiAbZLGtq5wzMTbxMdi7iIOO/F+zgmIguk9loihldsmCB4HqXPvxypiV2KMCAg5tv/MyjNe5gK86Et4rXPR4eZ347S3SdxG4+nkCmpU/BaYs8D/gUr6868woGsYLeNRCcG0IrCJ7BEAeZPwWZOa9egPCmEaMB5i2YA6Tfg+ibAPOIUSbmLYh2h/BWcHoLwnswRvgp+N5jhDdVb4CcgTbT+/sA4Lnw9uDkfXTPbuW8B/cD8hYM8uKAee/N4FzegRmLN4F7MecdmGkGeQdmzu805o1oma54aMz6f8RH3sOxTBfAkPYPy+zRPOBnj4lzOzA8yzQ1/j524Jpg9R5Gc7nxH4vvSSD23jrgyu3fOPGbqRBpe4V+DKoqMMsLOJk9VTd1HdADVAD0H0bo2Hqvvby7SZoaa4h73Q/RTexXWfo7KX6BDIAAAAAASUVORK5CYII=",
    "phoebe": "iVBORw0KGgoAAAANSUhEUgAAAFAAAABQCAMAAAC5zwKfAAAAMFBMVEUBAAAAAABGNTFtTEZzYGjIOFD0UZLDimrmsI/418j+/v6myvA2g/YgaOAQUMgoNmTzKOOYAAAAAXRSTlMAQObYZgAAAddJREFUeNrt10ua7SAIBOAgMaAhsP/d3tLbz2nDMNX29P8KzHkdb968eVOR3tPAL6VfV07cwIfSWqN+JcXrA7ygnQjlQQAXcq40yo/8C4RI8NIi0s52/j/Ue8bsvX940k7ZLKFztl/vTVUbDjV4eRDpuoI1psH+AZ4nQBG6CnbYAMIC6BN0/pZbw8Q0ARLAigex73J7ZM5X7CQsOsBtEF46RBC1X12EOryKkMh1wTvKwixMlR6JlHpDRUSpDtSdMpFkc6MKDLMl4p+LCtrK42Uzkz/Lc6kCITq84LKZIbk7HWUVWRFYXAXK+A9WVWTdIB9VFcEIQKmqCG9FIugouGgmICLuHhUXzaxuNqfNG2C+Ig8NM7vnnI85h+2KnOhI5LbF283FbVccI0HG/d97bINOAFl08J/BCREDuz2iC1xrJfr7Hn0u0dw26L5mhZaYGOMCW6Cq5j+nYtrK8jZ45MHV8LEy0G0C3AVdRx6MOb8Khox8xVjeygOQVYXSE6/c94MTLEhSjA8Qx4M4DxIHSvrqGBFpEBHhiBveAikPtn71dkS4e2ABVAB2gF8BKC0p/gJa+tft760BRNKfdx/gTnaJQwaPH0L60WZCfjXGHx2FgV/hvXnz5h/wARjaz86XzwAAAABJRU5ErkJggg==",
    "shauntal": "iVBORw0KGgoAAAANSUhEUgAAAFAAAABQCAMAAAC5zwKfAAAALVBMVEUAAABISFAYGBgwMDBgUJBIOGiQQEA4KEDYYGD4+PiQkKD40LjYoHi4eGB4SFh0nySGAAAAAXRSTlMAQObYZgAAAilJREFUeNrt1VeirDgMhGGpyrHT/pc7kjAnPPWAfTN/58BHxnJ1dXV1dXX1YyIpXvVWeKpKSM3Jy4MkcBaEWqxprxoJqipmwPBGObg5EOlr0AVgTnYf1TlQGF6AgwXNo5wNiiHtD8BInAcZYB1gTRkkCDkdDMy1BraDMx4VxvSea5RmQaoip97r4/G42Ut4X0RApHc94FlIt15bsScTv4EgtIR3EMzP5/1+v9V+ywEOkQpFK3LQC/HxuFspDW+AUAVxHDTx+Sjl/kgAv4DFvSPHJHSP5ItPQJVKHWCBgzgB8tUfrTWoF2J4jTRQIMfB5r00Co8wr5CEccdBhad7Y4WLGA05FD/EJ8gPbjA8fhHDh/e8byI95FrDew/eehev934LEY4g5XtOACMgWxX/w2OxjDStFBM9WHVcsBFJrS5yeO/F4lxru+hTYwyiu4Dq4ntviM04K8TwqiAzh7dXgbdeRCeBIQpgHgKIN2digeoQSUXGWPHTIpQozpU4LQIxNsCJsbgUqsXNQHIwpbMi6ZQnw9vKxNlFDGsPZA7OOilCvlSVWwCRILPVlBAaUqIf3vNeymDsKaRs+rRXXdGIqc6KNcf+2EHkPL2I1Thg8wgBZDaA5CZCVgSuB/+gReRKEOsWkVQlBEtAtCL72tLYeY/EvkPANSC/gJwHgSFCxPFpsBV8gFgAFgtkeGvW2QrIwNIaWWRFrsZA3QpkUaV5ZR2IEkGWhUh+fv8BQBURKnq5XxAAAAAASUVORK5CYII=",
    "sidney": "iVBORw0KGgoAAAANSUhEUgAAAFAAAABQCAMAAAC5zwKfAAAARVBMVEUBAAAAAAB7SlqWQ2J7N1E3PEjepHv/1b1RJDVeSSaee0FSWGm/nWMgIyvQt4z4+Pj////d3d2eNRveWjloL0Tu2cT+6NFCf+OIAAAAAXRSTlMAQObYZgAAAhJJREFUeF7t1MmS2yAURmHOZUaD3Z3h/R81FyzUyS4BNqny8YqFvvplqmT+vnfv3r17l1Z7lrUgdu1EtxhMztkEUwbwm2edtSkgE97n85MbtJpLMQbGvW/aJVJBV8E4BT6fHcRd3vhEPj6eHSRELi8GMRMipoMR4itZcMsSr2wD55MqBfXq0uFr4XcwVJFHVHcUbEvo4AOVvn9ELXAcQ6CIIUjXvxK27RgwiYKEe2JP2Pe8ace/g1Gi3GCoWoiRgILDYuDmw+Px+BklNHBU/ALlR6xJ6OAxNjHyx4HQFp74IbAh0kUROXMbWBQ8/DYkhhvE57NkeYHZwxBoJEQuz3vyiQTU1RObxsDEl4jXlNIzJfsaDRwRhdwIyPlEwVPF4YkSVNxpgvo5c571dDTRj00MqNifzbw8rcJjE9lL7ltAueaR8whoENlLyd3bQFqc5WREzMqVnctThtiq4o6CA+K+5/srRoEXGRgEDXB7EZxzQGx/LZjhOuheAbuCk164PGtTIzGzYKBxDXSYyQgVtBXEaWmOS8kRwK4CkwoW/anYwbl5ttXBWc9dnnP3OzPjdU7rEye9zt1gWuOlhGcWVO/mYlwA4jrnAK/gvNg5g9eYBQ2VBKX9LNgDzOWV+5Xng1IKClIzK2pOSsQgZmUSY1wqAktBtm0DFoIo6T3LuE1bB+Ibt3BgqSmYF14x5JzN/9a7X8b1FsE1851eAAAAAElFTkSuQmCC",
    "wallace": "iVBORw0KGgoAAAANSUhEUgAAAFAAAABQCAMAAAC5zwKfAAAALVBMVEUAAAAQEAAoaFBwcHB4SFiQOKDAYNDYiOC4uLho2MBIoIi4eGDYoHj44MD4+PjQBBkWAAAAAXRSTlMAQObYZgAAAsxJREFUeNrs0UmCwzAIRFEVsMACfP/jtkpKD9vQWfpnHvxsifH09PT09PR+8WHPyj4MRsWnRbN/AcrGb2GV9h/tZn9IW2IX3NrJtxgxLAOBnvfD/YiWhrSqtL73EwhGWias8AHQiSAzMqq1ifDXONxF5C+Y9JrgHotc8xL3I4Zl9wLdb3V3lXlRJHjEwmiC6gBSgEt+Qc00tEB6tcsj6ljh1jTviYqQOOCUKfQIck5viyJcnCVuihJY4Mtj+i4o15ShYrUL+AKhB9y97V0yZd1fIMcw4RTR8AgK5lxkFssMmRBfIrzpDcWU+7YKegmXKb5E3JNeB7y5OI0yW576EfWaHXDQY0sgR++AmPNaXiM9nmsCaQu0CD8gRidAl7LFtApDFfSA0gKVlmIRBK0qYUZvNr3XgnmFe9LIqoKsRhNkBDmWYgHwU99jDqjjeOthbRCH2ynqiMQp9kH2K9qcHwBVHbfuGSfFJghXP9wCFq4J+eq9TpQQCWEgDNt0hcny/g+8gXbYoYwXVu3vfX0Gbxt+AQNzds6BLoOl9QzYEunnAxiUjiI4WD0OcMdzed3RUaIBx3F0cXvAvq+jYGudGyI2XtUTDOhPeCW8ug3KUwwPaCW8Wk+Q33oLGFwrQI1seBvgxQtOz+4Aawfhzv0B3eVN0KrAHU+gt1IFYpgVdMdX3gWER7+A9DHf4lHOCaK1T0WS0haQwzIzeZ+B0rTYFZRnLZrge5GR3hj5gNZWUCLJnBuYvHRAA+WdD6FAp3tqissCuxfqAO0c8CJGzEH3DKxkhQ2wFIEoUYDwe9mIRKCZNwhzhnGzKvAWdRR3j8Bni56ehljAEfyM+MATaHWCwAJG4CSRg+75gNDVEFngCZmK9GzBNwD/fo09/LiGTCQvbKzrtQHacqVxj483Bvj6r7F7HwrAhdOEjAR+EnAHg0sD51P6YVAv3vK6+D/1FzdYPWykIU2kAAAAAElFTkSuQmCC",
    "will": "iVBORw0KGgoAAAANSUhEUgAAAFAAAABQCAMAAAC5zwKfAAAAM1BMVEUBAABCEywAAAAfHx9qGUqNJWJKLGLi4vZqYjs7OzupYkr2xanPjWLYsgeyJR98So1KM2r171AIAAAAAXRSTlMAQObYZgAAAm9JREFUeF7d1N9uo0AMxWHOsecvJN33f9q1rUlR9wqBb7q/FJRG4pNnINn+k2qtud7X11etuaCTzAQjZnkORpVJnIlpZFgMs6asO6AAF8oEr+41DWQoO88RM8B99xGZAYYoMneD/TAyA2xDdmOlBrk9jAY2IZuf60ecc970DBAZQo42ZHKtee72mjdBVMx9nyJiivkOYgJG3vyi4Dh2y9RaucD2fhs6b4HcTMQ0T2z/6EvG28OdERn3QObhi2bdPmDvrQG8A9Jd4AA03gZiXOvHcQP06ztZtHdVIT9E7+Hdqr+6UG0mkcHOAMBjHtB7IoRDSuutu7jAQhzUWyKKjCHDwSZjiSitkVTe8RYYDXEkQLWueQBODhr3QtqKwaAULZc9f2Q/XImKg6Kt9QAVWspVb+LdXFycqhbwD8VTO2giSoC8ws0Db6vDKp6WuI7ShWIne2vgVW9D/CrN3lBW4OaxvzrFTo7r+vxKmE62eaA1v47n0y0v++vion9+NQL7YeH0IvFohwNc3nUTmPzX+2zijaiWgTi9Iecm3gV/eEPOTbwRoYj1nuBYWyjcbkXipzeErJUOPi5A9l5rkmjIIID+er06c0CqBUspTPJKKXDW+McgYdwCQeFjT1AWCGgqCNUEkCIfMQ3kAqkKeQy6cILPHxsXcsEAsED4/xnxG0yKGmCWlw8CDHDLCkqUAuR5SkWB5oiAWoRCmeJpxFAzvVyQaSAWlA6GqEzzFohEUJE3YijKJNBaYMqa5Xuo8PB0RIpINvhTTABJLgRQYHsYzxnjhksmSJefdy5ZxjAxr/CsRNDIzCEpRlqJq2a0/fb+AgI8G/BatGJxAAAAAElFTkSuQmCC",
}


SINGLE_PORT = 47653


def claim_single_instance():
    """Make this the only running copy: if another one is open, ask it to
    close (it saves first), wait for it, and fall back to killing it."""
    import socket
    def bind():
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            srv.bind(("127.0.0.1", SINGLE_PORT))
            srv.listen(4)
            return srv
        except OSError:
            srv.close()
            return None
    srv = bind()
    if srv is not None:
        return srv
    try:
        with socket.create_connection(("127.0.0.1", SINGLE_PORT), 1) as c:
            c.sendall(b"quit")
    except OSError:
        pass
    for _ in range(40):
        time.sleep(0.15)
        srv = bind()
        if srv is not None:
            return srv
    if IS_WIN:  # it did not answer: end every other copy by name
        try:
            exe = Path(sys.executable).name if getattr(
                sys, "frozen", False) else None
            if exe:
                subprocess.run(
                    ["taskkill", "/F", "/IM", exe, "/FI",
                     f"PID ne {os.getpid()}", "/FI",
                     f"PID ne {os.getppid()}"],
                    capture_output=True, creationflags=0x08000000)
        except Exception:
            pass
        for _ in range(20):
            time.sleep(0.2)
            srv = bind()
            if srv is not None:
                return srv
    return None


def listen_for_quit(srv, app, root):
    def run():
        while True:
            try:
                conn, _addr = srv.accept()
                data = conn.recv(16)
                conn.close()
                if data == b"quit":
                    root.after(0, app.quit_app)
                    return
            except Exception:
                return
    threading.Thread(target=run, daemon=True).start()


if __name__ == "__main__":
    sys.excepthook = log_error
    write_log("run.log", datetime.now().isoformat() + " started "
              + VERSION + "\n")
    if IS_WIN and getattr(sys, "frozen", False):
        try:  # never stay attached to a console window
            ctypes.windll.kernel32.FreeConsole()
        except Exception:
            pass
    if IS_WIN:
        try:  # make Tk and window coordinates use the same (real) pixels
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
    single = claim_single_instance()
    root = tk.Tk()
    root.report_callback_exception = log_error
    root.title("PokeMmoHelper")
    app = Overlay(root)
    if single is not None:
        listen_for_quit(single, app, root)
    root.mainloop()
