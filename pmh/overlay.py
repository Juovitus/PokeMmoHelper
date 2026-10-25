"""The main window: title bar, checklist pages, updater, and following the
game window."""
from .guide_view import *  # noqa: F401,F403

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
            # start collapsed, so the full window never shows
            self.collapsed = True
            self.collapse_button.config(text="+")
            self.content.pack_forget()
            self.bottom.pack_forget()

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

    def gkeys(self, task, item):
        """Keys of an item's sub-checkboxes (one per labelled team)."""
        groups = item.get("teams")
        if not isinstance(groups, list):
            return []
        base = self.ckey(task, item)
        return [f"{base} >> {g['label']}" for g in groups
                if isinstance(g, dict) and g.get("label")]

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
        # Berry progress bar up the left side, filling upwards. Shown by
        # place_berry_bar only while berries are planted. It sits beside
        # the page dropdown (not under it), so opening that doesn't move it.
        self.title_bar = tk.Canvas(self.main_frame, width=16, bg=TRACK,
                                   highlightthickness=0, bd=0)
        self.title_bar_shown = False
        self.title_bar.bind("<Configure>", self.redraw_berry_bar)
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
        # Water-drop alert beside the page title (the berry bar itself runs
        # up the left side, see build_main).
        self.drop_image = tk.PhotoImage(data=DROP_PNG)
        self.alert_label = tk.Label(self.bar_frame, image=self.drop_image,
                                    bg=BAR)
        self.alert_shown = False
        self.alert_label.bind("<ButtonPress-1>", self.start_drag)
        self.alert_label.bind("<B1-Motion>", self.drag)
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
        # beside the berry bar when it shows, so the bar doesn't move
        self.page_menu.pack(fill="x", after=(
            self.title_bar if self.title_bar.winfo_manager()
            else self.accent_strip))
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
            # every page starts with a "Send Feedback" bar
            feedback_bar(frame, self, lambda name=self.page_name,
                         tasks=self.tasks, vars=self.vars, guides=self.guides:
                         self.page_details(name, tasks, vars, guides)
                         ).pack(fill="x", pady=(0, 6))
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

    def page_details(self, page_name, tasks, vars, guides):
        """What is sent along with a feedback comment: the planted berries,
        the open guides (where the user is in each), or the ticks."""
        if self.page_type == "berries" and self.berry_view is not None:
            return self.berry_view.feedback_details()
        if guides:
            open_ones = [g.feedback_details() for g in guides
                         if g.rendered and g.group is not None]
            return ("\n\n".join(open_ones) if open_ones else
                    f"Version: {VERSION}\nPage: {page_name} (no guide open)")
        lines = [f"Version: {VERSION}", f"Page: {page_name}"]
        for task in tasks:
            items = task.get("items") or []
            done = [i.get("name", "?") for i in items
                    if vars.get(child_key(page_name, task, i)) is not None
                    and vars[child_key(page_name, task, i)].get()]
            lines.append(f"{task['name']}: {len(done)}/{len(items)} done"
                         + (f" ({', '.join(done)})" if done else ""))
        return "\n".join(lines)

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
        self.build_team(details, item, task)
        if item.get("info"):
            self.add_text(details, str(item["info"]), FG, ("Segoe UI", 8))
        if item.get("note"):
            self.add_text(details, item["note"], DIM,
                          ("Segoe UI", 8, "italic"))
        has = bool(parse_team(item.get("team")) or item.get("teams")
                   or item.get("note") or item.get("info"))
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

    def build_team(self, parent, item, task=None):
        groups = item.get("teams")
        if isinstance(groups, list):
            # one labelled row of Pokemon per case ("Fire (Left):", ...),
            # each with its own checkbox
            # that folds away when ticked, like a gym does
            base = self.ckey(task, item) if task is not None else None
            for group in groups:
                if not isinstance(group, dict):
                    continue
                members = parse_team(group.get("team"))
                if not group.get("label") or base is None:
                    if group.get("label"):
                        tk.Label(parent, text=f"{group['label']}:", fg=FG,
                                 bg=BG, font=("Segoe UI", 8, "bold"),
                                 anchor="w").pack(fill="x", padx=(24, 0),
                                                  pady=(2, 0))
                    self.build_members(parent, members)
                    continue
                gkey = f"{base} >> {group['label']}"
                box = tk.Frame(parent, bg=BG)
                box.pack(fill="x")
                line = tk.Frame(box, bg=BG)
                line.pack(fill="x", padx=(24, 0), pady=(2, 0))
                var = tk.BooleanVar(value=gkey in self.done)
                self.vars[gkey] = var
                self.make_check(line, var, lambda t=task, i=item, k=gkey:
                                self.on_group(t, i, k)).pack(side="left",
                                                             padx=(0, 4))
                title = tk.Label(line, bg=BG, fg=FG, anchor="w",
                                 cursor="hand2",
                                 font=("Segoe UI", 8, "bold"))
                title.pack(side="left")
                title.bind("<Button-1>", lambda e, k=gkey: self.toggle_item(k))
                details = tk.Frame(box, bg=BG)
                self.build_members(details, members)
                self.item_rows[gkey] = {"title": title, "details": details,
                                        "has": True, "shown": False,
                                        "text": None,
                                        "label": f"{group['label']}:"}
                self.set_item_open(gkey, gkey not in self.closed)
        self.build_members(parent, parse_team(item.get("team")))

    def build_members(self, parent, members):
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
                for gkey in self.gkeys(task, item):
                    if gkey in self.vars:
                        self.vars[gkey].set(gkey in self.done)
                    if gkey in self.item_rows:
                        self.set_item_open(gkey, gkey not in self.closed)
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

    def place_berry_bar(self):
        """Show the berry bar (berries planted, window not collapsed): down
        the left side from the title bar to the bottom strip."""
        if self.title_bar_shown and not self.collapsed:
            self.title_bar.pack(side="left", fill="y", after=self.bottom)
        else:
            self.title_bar.pack_forget()

    def redraw_berry_bar(self, _event=None):
        """The bar changed size (window resized): paint it again."""
        self._title_state = None
        self.update_title_progress()

    def update_title_progress(self):
        """The berry bar up the left side (shown on every page) and the
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
        if bool(stats) != self.title_bar_shown:
            self.title_bar_shown = bool(stats)
            self.place_berry_bar()
        draw_bar(self.title_bar, fraction, color, text, default_w=16,
                 default_h=200, notches=notches, upward=True)
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
            for gkey in self.gkeys(task, item):
                self.set_done(gkey, value)
                self.set_closed(gkey, value)
            self.set_closed(ckey, value)  # done -> hidden, undone -> open
        self.save()
        if value:
            self.collapse(key)   # finished: fold it away (can be reopened)
        self.refresh_view()

    def on_group(self, task, item, gkey):
        """A sub-checkbox: ticking the last one ticks the item."""
        self.set_done(gkey, self.vars[gkey].get())
        self.set_closed(gkey, self.vars[gkey].get())  # done -> folded away
        ckey = self.ckey(task, item)
        all_done = all(k in self.done for k in self.gkeys(task, item))
        if all_done != (ckey in self.done):
            self.vars[ckey].set(all_done)
            self.on_child(task, item, from_group=True)
        else:
            self.save()
            self.refresh_view()

    def on_child(self, task, item, from_group=False):
        ckey = self.ckey(task, item)
        value = self.vars[ckey].get()
        self.set_done(ckey, value)
        if not from_group:
            for gkey in self.gkeys(task, item):
                self.set_done(gkey, value)
                self.set_closed(gkey, value)
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
        self.place_berry_bar()
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
                # the feedback window stays above the overlay
                win = getattr(self, "feedback_win", None)
                if win is not None and win.winfo_exists():
                    win.attributes("-topmost", True)
                    win.lift()
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
