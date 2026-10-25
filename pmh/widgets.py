"""Hand-drawn widgets: pin icon, flat buttons, progress bars."""
from .berry_data import *  # noqa: F401,F403

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
             notches=(), upward=False):
    """Paint a progress bar: a filled rectangle, watering ticks along the top
    and bottom edges (white = needs water, dark = already watered) and
    centred text with a dark outline so it stays readable on any colour.
    `upward`: a standing bar that fills from the bottom (text turned on its
    side, ticks along the left and right edges)."""
    width, height = canvas_size(canvas, default_w, default_h)
    canvas.delete("all")
    fraction = max(0.0, min(1.0, fraction))
    length, thick = (height, width) if upward else (width, height)
    if fraction > 0:
        filled = max(1, round(length * fraction))
        canvas.create_rectangle(*((0, height - filled, width, height)
                                  if upward else (0, 0, filled, height)),
                                fill=color, width=0)
    tick = max(3, thick // 4)       # ticks stay clear of the text
    for mark, watered in notches:
        at = min(max(round(length * mark), 1), length - 1)
        line = BG if watered else "#ffffff"
        if upward:
            y = height - at
            canvas.create_line(0, y, tick, y, width=2, fill=line)
            canvas.create_line(width - tick, y, width, y, width=2, fill=line)
        else:
            canvas.create_line(at, 0, at, tick, width=2, fill=line)
            canvas.create_line(at, height - tick, at, height, width=2,
                               fill=line)
    if text:
        cx, cy = width // 2, height // 2
        font = ("Segoe UI", 7, "bold")
        angle = 90 if upward else 0
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1),
                       (-1, -1), (1, 1), (-1, 1), (1, -1)):
            canvas.create_text(cx + dx, cy + dy, text=text, fill="#101114",
                               font=font, angle=angle)
        canvas.create_text(cx, cy, text=text, fill="#ffffff", font=font,
                           angle=angle)


def send_feedback(comment, details):
    """Post a comment and the details (where the user is) to the feedback
    Google Form. Returns None when it went through, else a short error."""
    import urllib.parse
    form, comment_field, details_field = FEEDBACK_FORM
    body = urllib.parse.urlencode({comment_field: comment[:4000],
                                   details_field: details[:20000]}).encode()
    req = urllib.request.Request(
        f"https://docs.google.com/forms/d/e/{form}/formResponse", data=body,
        headers={"User-Agent": "PokeMmoHelper",
                 "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return None if resp.status == 200 else f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}"
    except Exception as e:
        return "no connection" if isinstance(e, urllib.error.URLError) \
            else type(e).__name__


def open_feedback(app, details):
    """The feedback window: a comment box, a preview of `details` (sent
    along with it), Send and Cancel. Only one is open at a time."""
    old = getattr(app, "feedback_win", None)
    if old is not None and old.winfo_exists():
        old.lift()                  # only one at a time
        old.focus_force()
        return
    win = app.feedback_win = tk.Toplevel(app.root, bg=BG)
    win.title("Send feedback")
    win.transient(app.root)   # stays above the overlay
    win.attributes("-topmost", True)
    win.resizable(False, False)
    tk.Label(win, text="What's wrong, or what could be better?", bg=BG,
             fg=FG, font=("Segoe UI", 9, "bold")).pack(
        anchor="w", padx=10, pady=(10, 2))
    comment = tk.Text(win, width=48, height=6, bg=BAR, fg=FG, bd=0,
                      insertbackground=FG, wrap="word",
                      font=("Segoe UI", 9), padx=6, pady=4)
    comment.pack(padx=10, fill="x")
    comment.focus_set()
    tk.Label(win, text="Also sent (no personal info):", bg=BG, fg=DIM,
             font=("Segoe UI", 8)).pack(anchor="w", padx=10, pady=(8, 2))
    preview = tk.Text(win, width=48, height=7, bg=BAR, fg=DIM, bd=0,
                      wrap="word", font=("Segoe UI", 8), padx=6, pady=4)
    preview.insert("1.0", details)
    preview.config(state="disabled")
    preview.pack(padx=10, fill="x")
    row = tk.Frame(win, bg=BG)
    row.pack(fill="x", padx=10, pady=10)
    status = tk.Label(row, text="", bg=BG, fg=DIM, font=("Segoe UI", 8))
    status.pack(side="left")

    def done(error):
        if error:
            status.config(text=f"Couldn't send: {error}", fg=RED)
            sending[0] = False
        else:
            status.config(text="Sent, thanks!", fg=CHECK_GREEN)
            win.after(1500, win.destroy)

    sending = [False]

    def send():
        text = comment.get("1.0", "end").strip()
        if not text:
            status.config(text="Type a comment first.", fg=AMBER)
            return
        if sending[0]:
            return
        sending[0] = True
        status.config(text="Sending…", fg=DIM)
        # the thread only fills the queue; Tk is touched from here
        result = queue.Queue()
        threading.Thread(
            target=lambda: result.put(send_feedback(text, details)),
            daemon=True).start()

        def wait():
            if not win.winfo_exists():
                return              # closed while sending
            try:
                done(result.get_nowait())
            except queue.Empty:
                win.after(200, wait)
        win.after(200, wait)

    for text, command, fg in (("Cancel", win.destroy, DIM),
                              ("Send", send, ACCENT)):
        frame = tk.Frame(row, bg=BUTTON_BORDER)
        flat_button(frame, text, command, BAR, fg, HOVER,
                    font=("Segoe UI", 9, "bold"), padx=10,
                    pady=2).pack(padx=1, pady=1)
        frame.pack(side="right", padx=(6, 0))
    win.update_idletasks()
    x = app.root.winfo_rootx() + 20
    y = app.root.winfo_rooty() + 60
    win.geometry(f"+{x}+{y}")


def feedback_bar(parent, app, details):
    """A full-width bordered "Send Feedback" bar; `details()` says what is
    sent along with the comment."""
    frame = tk.Frame(parent, bg=BUTTON_BORDER)
    flat_button(frame, "✎  Send Feedback",
                lambda: open_feedback(app, details()), BAR, DIM, HOVER, FG,
                font=("Segoe UI", 8), pady=2).pack(fill="x", padx=1, pady=1)
    return frame
