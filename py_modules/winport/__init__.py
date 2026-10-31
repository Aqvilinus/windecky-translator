"""Windows parts of WinDecky Translator (Decky Translator for Decky Loader on Windows).

Upstream targets SteamOS: it captures the screen through PipeWire/gamescope, reads the Steam Deck controller through
hidraw/evdev and lets gamescope put Steam's UI layer (and with it the translation overlay) over the game. On Windows
each of these has its own module here, used by main.py when sys.platform == "win32". Windows gives controller input
only to the app in front, never to the plugin, so the shortcut is a keyboard hotkey a controller button can be mapped to:

  capture.py  screenshot of the foreground window with Windows.Graphics.Capture (any app, any graphics API)
  overlay.py  the translation overlay as a click-through, never-activated, topmost layered window
  clipboard.py  text on the clipboard, for the Paste button of the key dialogs
  hotkey.py   Ctrl+Alt+T as a system-wide hotkey while the plugin is on
  pause.py    Pause Game While Translating: suspend and resume the game's processes (psutil)

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
