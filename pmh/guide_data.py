"""Elite Four guide data and the text clean-up applied to it."""
from .win32 import *  # noqa: F401,F403

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
    # Gengar's +2 / +4 / +6 Sp.Atk is one / two / three Nasty Plots
    def nasty(m):
        n = int(m.group(1)) // 2
        return (("Nasty Plot" if n == 1 else f"{n}x Nasty Plot")
                + f" (+{m.group(1)} Sp.Atk)")
    text = re.sub(r"(?:(?<=^Encore, then )|(?<=Gengar )|(?<=Gengar, Encore, "
                  r"then ))\+([246])(?: Sp\.Atk|(?! (?:Sp\.Atk|Speed|Atk|Def|"
                  r"Sp\.Def|Accuracy)\b))(?!\w)(?!\.\w)",
                  nasty, text)
    # Volcarona's +N is N Quiver Dances, which raise three stats
    def quiver(m):
        n = int(m.group(2))
        dance = "Quiver Dance" if n == 1 else f"{n}x Quiver Dance"
        lead = "Volcarona, " if m.group(1) else "Volcarona uses "
        return f"{m.group(1) or ''}{lead}{dance} (+{n} Sp.Atk, Sp.Def, Speed)"
    text = re.sub(r"(\bto )?\bVolcarona \+(\d)(?: Sp\.Atk)?"
                  r"(?![\w.]| (?:Sp\.Def|Speed|Def|Atk)\b)", quiver, text)
    text = re.sub(r"\bQuiver Dance \+1(?!\d)",
                  "Quiver Dance (+1 Sp.Atk, Sp.Def, Speed)", text)
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


SHADOW_RE = re.compile(r"\b(?:All|Whole|Click) Shadow\b", re.I)
SWITCH_RE = re.compile(
    r"(switch to|teleport to|send in|sacrifice|double switch|encore sacrifice|let it switch)",
    re.I)


def trainer_slug(name):
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


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
