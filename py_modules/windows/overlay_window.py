"""The translation overlay window: click-through (WS_EX_TRANSPARENT), never activated (WS_EX_NOACTIVATE), topmost,
with per-pixel alpha (WS_EX_LAYERED, UpdateLayeredWindow). On Windows Big Picture is a normal window behind the
game, so Steam's UI can't carry the overlay as it does on SteamOS. Shown only while the captured window is in
front, so switching to another app hides it. Coordinates are capture pixels = screen pixels (the process is
per-monitor DPI aware)."""
import ctypes
import logging
import queue
import threading
from ctypes import wintypes

from overlay import render

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
user32.UpdateLayeredWindow.restype = wintypes.BOOL
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

    def __init__(self, on_error=None):
        """on_error(message): called (on the overlay thread) when the overlay stops working, once per new error."""
        self._on_error = on_error
        self._queue = queue.Queue()
        self._thread = None
        self._hwnd = None
        self._state = None
        self._target = None
        self._shown = False
        self._dib = None  # (width, height, memory DC, bitmap, old bitmap, bits): reused while the size stays
        self.error = None  # why the overlay can't be drawn (get_windows_status), None while it works

    def start(self):
        if self._thread is None or not self._thread.is_alive():  # first use, or the thread died: (re)start it
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
        self._hwnd = user32.CreateWindowExW(WS_EX_STYLE, CLASS_NAME, "WinDecky Translator", WS_POPUP, 0, 0, 1, 1,
                                            None, None, hinst, None)
        self._shown = False  # a new window (this thread may replace one that died)
        if not self._hwnd:
            self._fail(f"could not create the overlay window (error {ctypes.get_last_error()})")
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
                        # let go of the captured frame and the screen-sized bitmap (~20-80 MB) until the next show
                        self._state, self._target, draw = None, None, False
                        self._free_dib()
                if draw:
                    try:
                        self._draw()
                    except Exception as e:  # noqa: BLE001 - keep the thread alive
                        self._fail(f"draw failed: {e!r}")
                self._sync_visibility()
                while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as e:  # noqa: BLE001 - reported; the next show() starts a new thread
            self._fail(f"the overlay thread stopped: {e!r}")
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

    def _fail(self, error):
        """Log a drawing failure once (until the overlay works again) and keep it for get_windows_status."""
        if error != self.error:
            logger.error("overlay: %s", error)
            if self._on_error:
                self._on_error(error)
        self.error = error

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
            if user32.UpdateLayeredWindow(self._hwnd, screen, ctypes.byref(wintypes.POINT(mx, my)),
                                          ctypes.byref(wintypes.SIZE(mw, mh)), hdc, ctypes.byref(wintypes.POINT(0, 0)),
                                          0, ctypes.byref(blend), ULW_ALPHA):
                self.error = None
            else:
                self._fail(f"UpdateLayeredWindow failed (error {ctypes.get_last_error()})")
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
