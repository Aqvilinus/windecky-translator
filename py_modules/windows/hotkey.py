"""The translate shortcut on Windows: Ctrl+Alt+T as a system-wide hotkey, registered while the plugin is on.

XInput can't stand in for upstream's hidraw controller reading: on current Windows builds XInput (on GameInput) gives
button states only to the foreground app, and the plugin's backend never is. A keyboard shortcut reaches the backend
through RegisterHotKey whatever app is in front, and handheld vendor apps (OneXConsole) or Steam Input can map any
controller button to it. With the plugin switched off the combo keeps its normal meaning.

The hotkey and its message loop have a thread of their own that sleeps in GetMessage: no polling, no CPU while idle.
"""
import ctypes
import logging
import threading
from ctypes import wintypes

logger = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
WM_APP_ENABLE = 0x8001  # WM_APP + 1, wParam 1/0: register or unregister (a hotkey belongs to the thread that registers it)
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
HOTKEY_ID = 1
HOTKEY = (MOD_CONTROL | MOD_ALT, ord("T"), "Ctrl+Alt+T")


class Hotkey:
    """Ctrl+Alt+T; on_press runs on the hotkey's own thread."""

    def __init__(self, on_press):
        self._on_press = on_press
        self._tid = None
        self._ready = threading.Event()
        self.active = False
        self.error = None
        self._thread = threading.Thread(target=self._run, name="translator-hotkey", daemon=True)
        self._thread.start()
        self._ready.wait(5)

    # ---- hotkey thread
    def _set_registered(self, on):
        if on == self.active:
            return
        user32.UnregisterHotKey(None, HOTKEY_ID)
        self.active = False
        if on:
            if user32.RegisterHotKey(None, HOTKEY_ID, HOTKEY[0] | MOD_NOREPEAT, HOTKEY[1]):
                self.active, self.error = True, None
            else:
                self.error = ctypes.get_last_error()  # 1409: another program owns the combo
                logger.warning("%s is taken (error %s)", HOTKEY[2], self.error)

    def _run(self):
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # create this thread's message queue
        self._tid = threading.get_native_id()
        self._set_registered(True)
        self._ready.set()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_APP_ENABLE:
                self._set_registered(bool(msg.wParam))
            elif msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                try:
                    self._on_press()
                except Exception as e:  # noqa: BLE001 - never kill the loop
                    logger.error("hotkey handler failed: %r", e)
        self._set_registered(False)

    # ---- other threads
    def status(self):
        return {"hotkey": HOTKEY[2], "registered": self.active, "error": self.error}

    def set_enabled(self, on):
        """The plugin was switched on or off: off, Ctrl+Alt+T keeps its normal meaning."""
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_APP_ENABLE, int(bool(on)), 0)

    def close(self):
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            self._thread.join(2)
