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
