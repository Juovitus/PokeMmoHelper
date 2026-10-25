"""The Berry Planter page."""
from .widgets import *  # noqa: F401,F403

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

    def feedback_details(self):
        """The planted berries, sent along with a feedback comment."""
        lines = [f"Version: {VERSION}", "Page: Berry Planter",
                 f"Plants ({len(self.app.berry_plants)}):"]
        now = time.time()
        for plant in self.app.berry_plants:
            info = berry_info(plant["berry"], self.app.config)
            st = plant_status(plant, info, now)
            ready = ("ready" if st["state"] == "ready"
                     else f"ready in {fmt_duration(st['ready_in'])}")
            lines.append(f"  {plant['berry']}: {ready}")
        return "\n".join(lines)

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
