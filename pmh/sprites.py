"""Pokemon and item pictures: bundled copies or PokeAPI."""
from .images import *  # noqa: F401,F403

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
