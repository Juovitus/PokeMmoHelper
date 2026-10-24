"""The Elite Four guide view."""
from .berry_view import *  # noqa: F401,F403

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

    def rich(self, text, fg, font, pady=0, warn=None):
        """A line of text with the pictures of the Pokemon and items it
        names shown beside it, and an optional red warning after it. Steps
        arrive already cleaned (with the step before them in mind), so
        don't add "Encore, then" a second time."""
        text = clean_step(text, auto_encore=False)
        marks = find_mentions(text)[:4]
        if (not marks and getattr(self, "has_gengar", False)
                and re.match(r"\W*Encore\b", text)):
            marks = [("pokemon", "gengar")]   # Gengar is the one with Encore
        if not marks and not warn:
            return self.text(self.frame, text, fg, font, pady)
        row = tk.Frame(self.frame, bg=BG)
        row.pack(fill="x", pady=pady)
        if marks:
            strip = tk.Frame(row, bg=BG)
            strip.pack(side="left", anchor="n", padx=(0, 3))
        for kind, name in marks:
            pic = tk.Label(strip, bg=BG)
            pic.pack(side="left")
            self.picture(pic, kind, name, 3 if kind == "pokemon" else 1)
        label = tk.Label(row, text=text, bg=BG, fg=fg, font=font,
                         justify="left", anchor="w")
        label.pack(side="left", fill="x", expand=not warn)
        offset = 34 * len(marks)
        if warn:
            tk.Label(row, text=f"⚠ {warn}", bg=BG, fg=RED,
                     font=("Segoe UI", 8, "bold")).pack(
                side="left", padx=(6, 0))
            offset += 130
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
            lines = team_lines_first(shown)
            # the guide ends here (no more choices): the Shadow Ball plan
            # is the finish, so it gets the purple highlight
            ends = current and not (branch or {}).get("options")
            for pos, (kind, text) in enumerate(lines):
                if (kind == "warning" and pos
                        and lines[pos - 1][0] != "warning"):
                    continue          # shown on the step before it
                warn = (lines[pos + 1][1] if pos + 1 < len(lines)
                        and lines[pos + 1][0] == "warning" else None)
                if ends and kind != "warning" and SHADOW_RE.search(text):
                    # Shadow Ball only: hard to miss
                    self.rich(f"◆ {text}", SHADOW,
                              ("Segoe UI", 10, "bold"), pady=(2, 2),
                              warn=warn)
                elif kind != "setup" and SWITCH_RE.match(text):
                    # a switch YOU have to make: stands out in cyan
                    self.rich(f"⇄ {text}", SWITCH,
                              ("Segoe UI", 9, "bold"), warn=warn)
                elif kind == "setup":
                    self.rich(f"» {text}",
                              ACCENT if current else DIM, ("Segoe UI", 8),
                              warn=warn)
                elif kind == "note":
                    self.rich(f"· {text}", DIM,
                              ("Segoe UI", 8, "italic"), warn=warn)
                elif kind == "warning":
                    self.rich(f"⚠ {text}", RED,
                              ("Segoe UI", 8, "bold"))
                else:
                    self.rich(f"• {text}",
                              FG if current else DIM, ("Segoe UI", 9),
                              warn=warn)
        if branch:
            # an empty prompt means the buttons speak for themselves
            prompt = branch.get("prompt")
            if prompt != "":
                self.text(self.frame, prompt or "What happened?", AMBER,
                          ("Segoe UI", 8), pady=(6, 0))
            self.grid([(o["label"],
                        lambda o=o: self.pick_step(o["label"], o["nodeId"]))
                       for o in branch.get("options", [])], 2)
        else:
            self.restart_button(self.frame, "✓ Fight finished",
                                ("#1f4d2c", "#9be7a8", "#2e6b3e")).pack(
                anchor="w", pady=(6, 0))
