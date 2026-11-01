"""Thin wrappers over the Windows API, no plugin logic:

  capture.py         a frame of the foreground window (Windows.Graphics.Capture: any app, any graphics API)
  overlay_window.py  the click-through window that shows the translation over the game
  hotkey.py          Ctrl+Alt+T as a system-wide hotkey (Windows gives controller input only to the app in front, so
                     the shortcut is a key a controller button can be mapped to)
  clipboard.py       text on the clipboard, for the Paste button of the key dialogs
  pause.py           Pause Game While Translating (moves out to game_process.py)

The process is made per-monitor DPI aware once (each Decky plugin backend is its own process), so window rectangles,
captured frames and the overlay all use real screen pixels.
"""
import ctypes
import sys

if sys.platform == "win32":
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
    except (AttributeError, OSError):
        pass
