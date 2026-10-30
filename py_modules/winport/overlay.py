"""The translation overlay on Windows: a click-through, never-activated, topmost layered window.

Upstream renders the overlay (src/Overlay.tsx) in Steam's UI, which gamescope keeps above the game on SteamOS. On
Windows Big Picture is a normal window behind the game, and Steam's in-game overlay exists only in games Steam hooks,
so the overlay is a window of its own: WS_EX_LAYERED with per-pixel alpha (UpdateLayeredWindow), WS_EX_TRANSPARENT so
mouse input goes through, WS_EX_NOACTIVATE so it never takes focus, WS_EX_TOPMOST. It is independent of how the app
below draws. It is shown only while the captured window is the foreground window, so switching to another app hides it.

The frontend keeps upstream's overlay state (ImageState) and sends every change here (main.py native_overlay_update).
The drawing is Google Lens style: each label covers its OCR box in the largest font that fits (capped at the original
line height), on the colour around the box; it widens into free space like Overlay.tsx. The processing pill sits
bottom-left. Coordinates are capture pixels = screen pixels (the process is
per-monitor DPI aware); CSS sizes from Overlay.tsx are multiplied by the monitor's scale.
"""
import ctypes
import logging
import os
import queue
import threading
from ctypes import wintypes

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shcore = ctypes.WinDLL("shcore")

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                   wintypes.HINSTANCE, wintypes.LPVOID]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetAncestor.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.MonitorFromWindow.restype = wintypes.HMONITOR
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
shcore.GetDpiForMonitor.argtypes = [wintypes.HMONITOR, ctypes.c_int, ctypes.POINTER(wintypes.UINT),
                                    ctypes.POINTER(wintypes.UINT)]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsHungAppWindow.argtypes = [wintypes.HWND]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.c_void_p]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                wintypes.UINT]
user32.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.c_void_p, ctypes.c_void_p, wintypes.HDC,
                                       ctypes.c_void_p, wintypes.COLORREF, ctypes.c_void_p, wintypes.DWORD]
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.PeekMessageW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE  # 64-bit: without it the module handle came back truncated
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p, wintypes.HANDLE,
                                   wintypes.DWORD]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]

WS_POPUP = 0x80000000
WS_EX_STYLE = 0x00080000 | 0x00000020 | 0x00000008 | 0x08000000 | 0x00000080  # LAYERED TRANSPARENT TOPMOST NOACTIVATE TOOLWINDOW
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
HWND_TOPMOST = wintypes.HWND(-1)
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_NOOWNERZORDER = 0x0001, 0x0002, 0x0010, 0x0200
PM_REMOVE = 0x0001
ULW_ALPHA = 0x00000002
AC_SRC_OVER, AC_SRC_ALPHA = 0x00, 0x01
GA_ROOT = 2
MONITOR_DEFAULTTONEAREST = 2
CLASS_NAME = "DeckyTranslatorOverlay"
TICK_SECONDS = 0.2  # foreground check / topmost reassert

FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
FONT_LATIN = ("segoeui.ttf", "arial.ttf")       # Latin, Cyrillic, Greek
FONT_CJK = ("msyh.ttc", "YuGothM.ttc", "msgothic.ttc")
FONT_HANGUL = ("malgun.ttf", "msyh.ttc")


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte), ("SourceConstantAlpha", ctypes.c_ubyte),
                ("AlphaFormat", ctypes.c_ubyte)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD)]


# ---------------------------------------------------------------- fonts and text layout
_fonts = {}


def _font_file(text):
    if any(0xAC00 <= ord(c) <= 0xD7AF for c in text):
        names = FONT_HANGUL
    elif any(ord(c) >= 0x2E80 for c in text):
        names = FONT_CJK
    else:
        names = FONT_LATIN
    for n in names:
        p = os.path.join(FONT_DIR, n)
        if os.path.exists(p):
            return p
    return None


def font_for(text, size):
    path = _font_file(text)
    key = (path, int(size))
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(path, int(size)) if path else ImageFont.load_default(int(size))
    return _fonts[key]


def wrap(text, font, max_width):
    """Lines of text that fit max_width (words; characters for text without spaces, e.g. CJK)."""
    out = []
    for para in text.split("\n"):
        tokens = para.split(" ") if " " in para else list(para)
        sep = " " if " " in para else ""
        cur = ""
        for t in tokens:
            cand = t if not cur else cur + sep + t
            if not cur or font.getlength(cand) <= max_width:
                cur = cand
            else:
                out.append(cur)
                cur = t
        out.append(cur)
    return out


# ---------------------------------------------------------------- drawing
def render(state, target, mon, scale, image=None):
    """The overlay image for the monitor rectangle mon = (left, top, width, height). image: the captured frame
    (PIL, capture pixels).

    As in Overlay.tsx the overlay is a still: the captured frame covers the window, the translations sit on it, and a
    thin border marks it (red: translations shown, amber: hidden). The game keeps running underneath unseen, so the
    labels never go stale; the shortcut closes the still and shows the live game again."""
    mx, my, mw, mh = mon
    img = Image.new("RGBA", (mw, mh), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ox, oy = target["left"] - mx, target["top"] - my  # capture origin inside the image
    tw, th = target["width"], target["height"]
    regions = state.get("regions") or []
    loading = bool(state.get("loading"))

    if image is not None:
        img.paste(image, (ox, oy))
        border = (244, 67, 54, 255) if state.get("translationsVisible", True) else (255, 193, 7, 255)
        d.rectangle((ox, oy, ox + tw - 1, oy + th - 1), outline=border, width=max(1, int(scale)))

    if state.get("translationsVisible", True) and regions and not loading:
        _draw_labels(d, regions, ox, oy, tw, state, scale, image)

    if loading and state.get("processingStep"):
        _draw_pill(d, state, ox + int(20 * scale), oy + th - int(20 * scale), scale)
    elif not state.get("translationsVisible", True) and not loading:
        r = int(22 * scale)
        cx, cy = ox + int(20 * scale) + r, oy + th - int(20 * scale) - r
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(0, 0, 0, 178))
        d.ellipse((cx - r // 2, cy - r // 3, cx + r // 2, cy + r // 3), outline=(255, 193, 7, 255), width=max(2, int(2 * scale)))
        d.line((cx - r // 2, cy - r // 2, cx + r // 2, cy + r // 2), fill=(255, 193, 7, 255), width=max(2, int(2 * scale)))
    return img


LINE_SPACING = 1.15
FONT_PER_LINE = 0.95  # font size (em) per pixel of an OCR line box's height
LABEL_ALPHA = 245     # nearly opaque, so the original text doesn't show through


def _fit(text, width, height, max_size, min_size):
    """Largest integer font size (<= max_size) whose wrapped text fits width x height, with its lines.
    None if even min_size doesn't fit."""
    best = None
    lo, hi = int(min_size), int(max_size)
    while lo <= hi:
        mid = (lo + hi) // 2
        font = font_for(text, mid)
        lines = wrap(text, font, width)
        widest = max((font.getlength(line) for line in lines), default=0)
        if widest <= width and len(lines) * mid * LINE_SPACING <= height:
            best = (mid, font, lines)
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _background(image, box):
    """Median colour of a thin ring around the box in the captured frame (the text's background)."""
    if image is None:
        return None
    x0, y0, x1, y1 = (int(v) for v in box)
    w, h = image.size
    ring = [(max(0, x0 - 3), max(0, y0 - 3), min(w, x1 + 3), max(0, y0)),          # above
            (max(0, x0 - 3), min(h, y1), min(w, x1 + 3), min(h, y1 + 3)),          # below
            (max(0, x0 - 3), max(0, y0), max(0, x0), min(h, y1)),                  # left
            (min(w, x1), max(0, y0), min(w, x1 + 3), min(h, y1))]                  # right
    channels = ([], [], [])
    for b in ring:
        if b[2] > b[0] and b[3] > b[1]:
            data = image.crop(b).convert("RGB").tobytes()  # (Image.getdata goes away in Pillow 14)
            for c in range(3):
                channels[c].extend(data[c::3])
    if not channels[0]:
        return None
    return tuple(sorted(ch)[len(ch) // 2] for ch in channels)


def auto_alignments(boxes, scale):
    """Alignment of each box's translation, as the original is laid out: a box that shares its left edge with a box
    stacked next to it (a list of choices) is left-aligned, its right edge right-aligned, anything else centred (its
    box hugs the original text, so the translation stays where the original was)."""
    tol = 8 * scale

    def stacked(a, b):
        return min(abs(a[1] - b[3]), abs(b[1] - a[3])) <= 1.5 * max(a[3] - a[1], b[3] - b[1])

    out = []
    for i, a in enumerate(boxes):
        near = [b for j, b in enumerate(boxes) if j != i and stacked(a, b)]
        out.append("left" if any(abs(a[0] - b[0]) <= tol for b in near)
                   else "right" if any(abs(a[2] - b[2]) <= tol for b in near) else "center")
    return out


def paragraphs(regions, boxes):
    """Paragraph id and line height of each box. Lines stacked within a line's height of each other, overlapping
    horizontally, are one paragraph, and its line height is its tallest line's: a box is only as high as its glyphs,
    so a line without tall letters ("mouse.") has a box about half a line high."""
    own = [(y1 - y0) / max(1, len([t for t in (r.get("text") or "").split("\n") if t.strip()]))
           for r, (x0, y0, x1, y1) in zip(regions, boxes)]
    group = list(range(len(boxes)))
    for i, a in enumerate(boxes):
        for j, b in enumerate(boxes):
            gap = max(b[1] - a[3], a[1] - b[3])
            if group[i] != group[j] and min(a[2], b[2]) > max(a[0], b[0]) and gap <= max(own[i], own[j]):
                old = group[j]
                group = [group[i] if g == old else g for g in group]
    tallest = {}
    for g, h in zip(group, own):
        tallest[g] = max(tallest.get(g, 0), h)
    return group, [tallest[g] for g in group]


def _draw_labels(d, regions, ox, oy, img_width, state, scale, image=None):
    """Google Lens style, the same rules for every label: the translation covers its OCR box on the box's own
    background colour, aligned as the original (auto_alignments), in its paragraph's line size. It may reach a line's
    height past its box into free space (never over another box or past the screen edge). A paragraph's lines share
    one size: the one its longest translation fits in."""
    pad = 2 * scale
    font_scale = float(state.get("fontScale") or 1.0)
    boxes = [tuple((r.get("rect") or {}).get(k, 0) for k in ("left", "top", "right", "bottom")) for r in regions]
    aligns = auto_alignments(boxes, scale)
    group, line_px = paragraphs(regions, boxes)

    def layout(i, max_size):
        """(size, font, lines, room) of label i, at most max_size."""
        x0, y0, x1, y1 = boxes[i]
        text = (regions[i].get("translatedText") or regions[i].get("text") or "").strip()
        n_lines = max(1, len([t for t in (regions[i].get("text") or "").split("\n") if t.strip()]))
        left, right = max(pad, x0 - line_px[i]), min(img_width - pad, x1 + line_px[i])
        for u0, v0, u1, v1 in boxes:
            if y0 < v1 and y1 > v0:
                if u0 >= x1:
                    right = min(right, u0 - pad)
                elif u1 <= x0:
                    left = max(left, u1 + pad)
        cx = (x0 + x1) / 2
        room = {"left": right - x0, "right": x1 - left}.get(aligns[i], 2 * min(cx - left, right - cx))
        width = room + 2 * pad - 4 * scale
        height = max(y1 - y0, n_lines * line_px[i]) + 2 * pad
        smallest = max(8 * scale, max_size * 0.55)
        fit = _fit(text, width, height, max_size, smallest)
        if fit is None:  # too long even small: smallest size, the label grows downwards
            font = font_for(text, int(smallest))
            fit = (font.size, font, wrap(text, font, width))
        return fit + (height,)

    shown = [i for i, (r, b) in enumerate(zip(regions, boxes))
             if (r.get("translatedText") or r.get("text") or "").strip() and b[2] > b[0] and b[3] > b[1]]
    size = {}
    for i in shown:
        own = layout(i, max(8 * scale, line_px[i] * FONT_PER_LINE * font_scale))[0]
        size[group[i]] = min(size.get(group[i], own), own)

    for i in shown:
        r, (x0, y0, x1, y1), align = regions[i], boxes[i], aligns[i]
        font_size, font, lines, height = layout(i, size[group[i]])
        line_h = font_size * LINE_SPACING
        label_w = max(x1 - x0 + 2 * pad, max(font.getlength(t) for t in lines) + 4 * scale)
        label_h = max(height, len(lines) * line_h)
        cx = (x0 + x1) / 2
        lx = {"left": x0 - pad, "right": x1 + pad - label_w}.get(align, cx - label_w / 2) + ox
        ly = (y0 + y1) / 2 - label_h / 2 + oy  # centred on the box (a short line's box is lower than its text)

        bg = _background(image, (x0, y0, x1, y1)) if image is not None else None
        if bg is None and isinstance(r.get("bgColor"), list) and len(r["bgColor"]) >= 3:
            bg = tuple(r["bgColor"][:3])
        bg = bg or (0, 0, 0)
        fg = (20, 20, 20, 255) if 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2] > 150 else (255, 255, 255, 255)
        d.rounded_rectangle((lx, ly, lx + label_w, ly + label_h), radius=max(1, int(3 * scale)), fill=bg + (LABEL_ALPHA,))

        ty = ly + (label_h - len(lines) * line_h) / 2
        for t in lines:
            lw = font.getlength(t)
            tx = {"left": lx + 2 * scale, "right": lx + label_w - 2 * scale - lw}.get(align, lx + (label_w - lw) / 2)
            d.text((tx, ty + line_h / 2), t, font=font, fill=fg, anchor="lm")
            ty += line_h


def _draw_pill(d, state, x, bottom, scale):
    step = state.get("processingStep") or ""
    is_error = bool(state.get("processingIsError"))
    detail = "" if is_error else (state.get("processingDetail") or "")
    title = step if is_error else step + "..."
    f1 = font_for(title, 14 * scale)
    f2 = font_for(detail, 10 * scale) if detail else None
    icon = 18 * scale
    text_w = max(f1.getlength(title), f2.getlength(detail) if f2 else 0)
    h = 14 * scale * 1.3 + (10 * scale * 1.3 if f2 else 0) + 16 * scale
    w = 12 * scale + icon + 10 * scale + text_w + 12 * scale
    y = bottom - h
    d.rounded_rectangle((x, y, x + w, bottom), radius=int(h / 2), fill=(0, 0, 0, 178))
    ix, iy = x + 12 * scale, y + (h - icon) / 2
    if is_error:
        d.polygon([(ix + icon / 2, iy), (ix + icon, iy + icon), (ix, iy + icon)], fill=(255, 107, 107, 255))
    else:
        d.arc((ix, iy, ix + icon, iy + icon), 200, 120, fill=(52, 152, 219, 255), width=max(2, int(3 * scale)))
    tx = ix + icon + 10 * scale
    d.text((tx, y + 8 * scale), title, font=f1, fill=(255, 255, 255, 255))
    if f2:
        d.text((tx, y + 8 * scale + 14 * scale * 1.3), detail, font=f2, fill=(255, 255, 255, 178))


# ---------------------------------------------------------------- the window
# module level: the registered window class keeps pointing at it for the life of the process
_WNDPROC = WNDPROC(lambda h, m, w, l: user32.DefWindowProcW(h, m, w, l))


def _is_ghost_of(hwnd, target):
    """A paused game stops answering messages, and after a few seconds Windows may put a "Not responding" ghost window
    (class "Ghost", owned by dwm) in its place: that still is the game."""
    if not hwnd or not user32.IsHungAppWindow(wintypes.HWND(target)):
        return False
    buf = ctypes.create_unicode_buffer(16)
    user32.GetClassNameW(hwnd, buf, 16)
    return buf.value == "Ghost"


class Overlay:
    """Owns the overlay window on its own thread; show()/hide() can be called from any thread."""

    def __init__(self):
        self._queue = queue.Queue()
        self._thread = None
        self._hwnd = None
        self._state = None
        self._target = None
        self._shown = False
        self._dib = None  # (width, height, memory DC, bitmap, old bitmap, bits): reused while the size stays

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="translator-overlay", daemon=True)
            self._thread.start()

    def show(self, state, target):
        """state: upstream's overlay state (Overlay.tsx props); target: the captured window (Capture fields)."""
        self.start()
        self._queue.put(("show", state, target))

    def hide(self):
        self._queue.put(("hide", None, None))

    def stop(self):
        if self._thread:
            self._queue.put(("stop", None, None))
            self._thread.join(timeout=2)
            self._thread = None

    @property
    def hwnd(self):
        return self._hwnd

    # -- overlay thread
    def _run(self):
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW(lpfnWndProc=_WNDPROC, hInstance=hinst, lpszClassName=CLASS_NAME)
        user32.RegisterClassW(ctypes.byref(wc))  # fails harmlessly if a previous overlay thread registered it
        self._hwnd = user32.CreateWindowExW(WS_EX_STYLE, CLASS_NAME, "Decky Translator", WS_POPUP, 0, 0, 1, 1,
                                            None, None, hinst, None)
        msg = wintypes.MSG()
        try:
            while True:
                try:
                    cmds = [self._queue.get(timeout=TICK_SECONDS)]
                except queue.Empty:
                    cmds = []
                while True:  # take what queued up meanwhile: only the newest state gets drawn
                    try:
                        cmds.append(self._queue.get_nowait())
                    except queue.Empty:
                        break
                if any(c[0] == "stop" for c in cmds):
                    break
                draw = False
                for cmd, state, target in cmds:
                    if cmd == "show":
                        self._state, self._target, draw = state, target, True
                    elif cmd == "hide":
                        self._state, draw = None, False
                if draw:
                    try:
                        self._draw()
                    except Exception as e:  # noqa: BLE001 - keep the thread alive
                        logger.error("overlay draw failed: %r", e)
                self._sync_visibility()
                while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            self._free_dib()
            user32.DestroyWindow(self._hwnd)
            self._hwnd = None

    def _monitor(self):
        tgt = self._target or {}
        hwnd = wintypes.HWND(tgt.get("hwnd") or 0)
        mon = user32.MonitorFromWindow(hwnd if tgt.get("hwnd") else user32.GetForegroundWindow(), MONITOR_DEFAULTTONEAREST)
        mi = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
        user32.GetMonitorInfoW(mon, ctypes.byref(mi))
        r = mi.rcMonitor
        # the monitor's scale (GetDpiForWindow would give 96 for a DPI-unaware game on a 150 % screen)
        dpi_x, dpi_y = wintypes.UINT(0), wintypes.UINT(0)
        if shcore.GetDpiForMonitor(mon, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) != 0:  # MDT_EFFECTIVE_DPI
            dpi_x.value = 96
        return (r.left, r.top, r.right - r.left, r.bottom - r.top), (dpi_x.value or 96) / 96

    def _frame(self):
        """The captured frame of the current target (PIL RGB, decoded by the capture), for the still and the label
        background colours."""
        return (self._target or {}).get("image")

    def _draw(self):
        mon, scale = self._monitor()
        tgt = dict(self._target or {})
        if not tgt.get("width"):
            tgt.update(left=mon[0], top=mon[1], width=mon[2], height=mon[3])
        img = render(self._state or {}, tgt, mon, scale, self._frame())
        self._upload(img, mon)

    def _dib_for(self, mw, mh, screen):
        """The 32-bit top-down DIB section the layered window is updated from, made once per size."""
        if self._dib and self._dib[:2] == (mw, mh):
            return self._dib
        self._free_dib()
        hdc = gdi32.CreateCompatibleDC(screen)
        bmi = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=mw, biHeight=-mh, biPlanes=1, biBitCount=32)
        bits = ctypes.c_void_p()
        hbmp = gdi32.CreateDIBSection(hdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        if not hbmp:
            gdi32.DeleteDC(hdc)
            raise OSError("CreateDIBSection failed")
        old = gdi32.SelectObject(hdc, hbmp)
        self._dib = (mw, mh, hdc, hbmp, old, bits)
        return self._dib

    def _free_dib(self):
        if self._dib:
            _, _, hdc, hbmp, old, _ = self._dib
            gdi32.SelectObject(hdc, old)
            gdi32.DeleteObject(hbmp)
            gdi32.DeleteDC(hdc)
            self._dib = None

    def _upload(self, img, mon):
        mx, my, mw, mh = mon
        data = img.convert("RGBa").tobytes("raw", "BGRa")  # premultiplied BGRA, what UpdateLayeredWindow takes
        screen = user32.GetDC(None)
        try:
            _, _, hdc, _, _, bits = self._dib_for(mw, mh, screen)
            ctypes.memmove(bits, data, len(data))
            blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
            user32.UpdateLayeredWindow(self._hwnd, screen, ctypes.byref(wintypes.POINT(mx, my)),
                                       ctypes.byref(wintypes.SIZE(mw, mh)), hdc, ctypes.byref(wintypes.POINT(0, 0)), 0,
                                       ctypes.byref(blend), ULW_ALPHA)
        finally:
            user32.ReleaseDC(None, screen)

    def _sync_visibility(self):
        want = self._state is not None and bool(self._state.get("visible", True))
        tgt = (self._target or {}).get("hwnd")
        if want and tgt:
            if not user32.IsWindow(wintypes.HWND(tgt)):
                want = False
            else:
                fg = user32.GetForegroundWindow()
                fg = user32.GetAncestor(fg, GA_ROOT) or fg
                want = int(fg or 0) == int(tgt) or _is_ghost_of(fg, tgt)
        if want:
            user32.SetWindowPos(self._hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_NOOWNERZORDER)
            if not self._shown:
                user32.ShowWindow(self._hwnd, SW_SHOWNOACTIVATE)
                self._shown = True
        elif self._shown:
            user32.ShowWindow(self._hwnd, SW_HIDE)
            self._shown = False
