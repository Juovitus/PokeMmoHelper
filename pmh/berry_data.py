"""Berry growth times, plant status and formatting."""
from .guide_data import *  # noqa: F401,F403

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
