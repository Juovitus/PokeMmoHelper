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
import sys
import time
import tkinter as tk

from pmh.overlay import *  # noqa: F401,F403


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
