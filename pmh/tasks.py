"""Gym checklist pages: built-in defaults and tasks.json loading."""
from .config import *  # noqa: F401,F403

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

# An item can also have "teams": [{"label", "team"}, ...] when the team
# depends on something (which Striaton leader you face).
STRIATON_TEAMS = [
    {"label": "Fire (Left)",
     "team": "Aerodactyl Rock Slide + Blastoise Water Spout"},
    {"label": "Grass (Middle)",
     "team": "Togekiss Hyper Voice + Vanilluxe Blizzard"},
    {"label": "Water (Right)",
     "team": "Togekiss Hyper Voice + Typhlosion Eruption"},
]

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
             "team": "Aerodactyl Rock Slide + Typhlosion Eruption",
             "note": "Aerodactyl Protect against Durant or Flygon only if "
                     "they lead."},
            {"name": "Morimoto", "number": False,
             "team": "Garchomp Earthquake (lead)",
             "note": "Use mainly super effective moves. Keep Garchomp "
                     "alive, switch if needed."},
            {"name": "Striaton City",
             "teams": STRIATON_TEAMS,
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
             "note": "Garchomp Earthquake if Typhlosion faints."},
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


def fix_gyms(pages_raw, config):
    """One-time edits to gyms in an existing tasks.json (only where the
    user hasn't changed them)."""
    done = set(config.get("gym_fixes") or [])
    changed = False
    for page in pages_raw.get("pages", []):
        if not isinstance(page, dict) or page.get("name") != "Gym Tracker":
            continue
        for task in page.get("tasks") or []:
            for item in (task.get("items") or []
                         if isinstance(task, dict) else []):
                if not isinstance(item, dict):
                    continue
                if (item.get("name") == "Castelia City"
                        and "castelia" not in done and item.get("team")
                        == "Aerodactyl Rock Slide/Protect + "
                           "Typhlosion Eruption"):
                    item["team"] = "Aerodactyl Rock Slide + Typhlosion Eruption"
                    changed = True
                if (item.get("name") == "Striaton City"
                        and "striaton" not in done
                        and str(item.get("info", "")).startswith("Fire: ")
                        and not item.get("teams")):
                    item.pop("info", None)
                    item["teams"] = copy.deepcopy(STRIATON_TEAMS)
                    changed = True
                if (item.get("name") == "Striaton City"
                        and "striaton_water" not in done):
                    for group in item.get("teams") or []:
                        if (isinstance(group, dict)
                                and group.get("label") == "Water"
                                and group.get("team") == "Typhlosion Eruption"):
                            group["team"] = ("Togekiss Hyper Voice + "
                                             "Typhlosion Eruption")
                            changed = True
                if (item.get("name") == "Striaton City"
                        and "striaton_labels" not in done):
                    names = {"Fire": "Fire (Left)", "Grass": "Grass (Middle)",
                             "Water": "Water (Right)"}
                    for group in item.get("teams") or []:
                        if (isinstance(group, dict)
                                and group.get("label") in names):
                            group["label"] = names[group["label"]]
                            changed = True
                if (item.get("name") == "Nacrene City"
                        and "nacrene" not in done and item.get("note")
                        == "Garchomp Earthquake if Typhlosion faints. END OF "
                           "FIRST HOUR here."):
                    item["note"] = "Garchomp Earthquake if Typhlosion faints."
                    changed = True
    config["gym_fixes"] = sorted(done | {"castelia", "striaton",
                                         "striaton_water", "striaton_labels",
                                         "nacrene"})
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
        fixes_before = list(config.get("gym_fixes") or [])
        if seed_gyms(pages_raw, config):
            changed = True
        if fix_gyms(pages_raw, config):
            changed = True
        if (config.get("seeded_gyms") != before
                or config.get("gym_fixes") != fixes_before or changed):
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
