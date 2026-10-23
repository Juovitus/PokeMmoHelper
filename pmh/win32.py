"""Finding the PokeMMO window on Windows."""
from .sprites import *  # noqa: F401,F403
from .config import _clean

# ----------------------------------------------------------- window lookup
def list_big_windows(min_w=500, min_h=350):
    """Visible, non-minimized windows of at least min_w x min_h, as
    (title, class_name, (left, top, right, bottom), hwnd) where the rectangle
    is the window's drawable area on screen (below the title bar). Only
    titles, class names and geometry are read - nothing from other programs'
    memory."""
    if not IS_WIN:
        return []
    user32 = ctypes.windll.user32
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR,
                                      ctypes.c_int]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR,
                                     ctypes.c_int]
    user32.GetWindowRect.argtypes = [wintypes.HWND,
                                     ctypes.POINTER(wintypes.RECT)]
    user32.GetClientRect.argtypes = [wintypes.HWND,
                                     ctypes.POINTER(wintypes.RECT)]
    user32.ClientToScreen.argtypes = [wintypes.HWND,
                                      ctypes.POINTER(wintypes.POINT)]
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _):
        try:
            if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
                wr = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(wr))
                if (wr.right - wr.left >= min_w
                        and wr.bottom - wr.top >= min_h):
                    title = ""
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length:
                        tbuf = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, tbuf, length + 1)
                        title = tbuf.value
                    cbuf = ctypes.create_unicode_buffer(256)
                    user32.GetClassNameW(hwnd, cbuf, 256)
                    left, top, right, bottom = (wr.left, wr.top, wr.right,
                                                wr.bottom)
                    # Prefer the client area so we pin inside the game view,
                    # not to the title bar or invisible resize borders.
                    pt = wintypes.POINT(0, 0)
                    cr = wintypes.RECT()
                    if (user32.ClientToScreen(hwnd, ctypes.byref(pt))
                            and user32.GetClientRect(hwnd, ctypes.byref(cr))
                            and cr.right > 0 and cr.bottom > 0):
                        left, top = pt.x, pt.y
                        right, bottom = pt.x + cr.right, pt.y + cr.bottom
                    out.append((title, cbuf.value,
                                (left, top, right, bottom), hwnd))
        except Exception:
            pass
        return True

    user32.EnumWindows(callback, 0)
    return out


def match_tier(title, cls):
    """How well a window matches the game: 0 best, 2 weakest, None no match.
      0: title is PokeMMO (ignoring odd/invisible characters)
      1: title contains PokeMMO and the class is the game's class
      2: class is the game's class (fallback if the title can't be matched)"""
    t, c = _clean(title), _clean(cls)
    if t == _clean(GAME_TITLE):
        return 0
    if c == _clean(GAME_CLASS):
        return 1 if _clean(GAME_TITLE) in t else 2
    return None


def find_game_window():
    """Return (rect, title, hwnd) for the game window, or None. Best match
    tier wins; among equals, the largest window. Browser tabs that merely
    mention the game never match (wrong title and wrong class)."""
    best_key, chosen = None, None
    for title, cls, rect, hwnd in list_big_windows(300, 200):
        tier = match_tier(title, cls)
        if tier is None:
            continue
        key = (tier, -(rect[2] - rect[0]) * (rect[3] - rect[1]))
        if best_key is None or key < best_key:
            best_key, chosen = key, (rect, title, hwnd)
    return chosen
