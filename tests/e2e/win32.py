"""Win32 side of the end-to-end tests: what is really on screen, and real keyboard input.

Run with the plugin's own Python (bin/python314/python/python.exe -I tests/e2e/win32.py <command> ...), which has
Pillow in bin/py_modules. Every command prints one JSON line.

  state <title-regex>          foreground window, the translation overlay window, the first visible window whose
                               title matches
  focus <title-regex>          bring that window to the front
  keys <combo>                 press a combination with SendInput, e.g. ctrl+alt+t
  grab <x> <y> <w> <h> <out>   screenshot of a screen rectangle (PNG)
  diff <a.png> <b.png>         mean absolute pixel difference of two screenshots (0-255)
"""
import ctypes
import json
import os
import re
import sys
import time
from ctypes import wintypes

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "bin", "py_modules"))

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetForegroundWindow.restype = wintypes.HWND
user32.FindWindowW.restype = wintypes.HWND
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.IsIconic.argtypes = [wintypes.HWND]
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

OVERLAY_CLASS = "DeckyTranslatorOverlay"  # py_modules/winport/overlay.py CLASS_NAME


def title(hwnd):
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def rect(hwnd):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return [r.left, r.top, r.right - r.left, r.bottom - r.top]


def describe(hwnd):
    if not hwnd:
        return None
    return {"hwnd": int(hwnd), "title": title(hwnd), "visible": bool(user32.IsWindowVisible(hwnd)), "rect": rect(hwnd)}


def find(pattern):
    rx = re.compile(pattern)
    found = []

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and rx.search(title(hwnd) or ""):
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found[0] if found else None


def state(pattern=None):
    fg = user32.GetForegroundWindow()
    overlay = user32.FindWindowW(OVERLAY_CLASS, None)
    return {"foreground": describe(fg), "overlay": describe(overlay), "target": describe(find(pattern)) if pattern else None}


# SendInput
INPUT_KEYBOARD, KEYEVENTF_KEYUP = 1, 0x2
VK = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B, "tab": 0x09, "esc": 0x1B, "enter": 0x0D}


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def vk(name):
    name = name.lower()
    if name in VK:
        return VK[name]
    if len(name) == 1:
        return ord(name.upper())
    raise SystemExit(f"unknown key {name}")


def keys(combo):
    codes = [vk(k) for k in combo.split("+")]
    events = [INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=c)) for c in codes]
    events += [INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=c, dwFlags=KEYEVENTF_KEYUP)) for c in reversed(codes)]
    arr = (INPUT * len(events))(*events)
    sent = user32.SendInput(len(events), arr, ctypes.sizeof(INPUT))
    return {"sent": sent, "of": len(events)}


def focus(pattern):
    hwnd = find(pattern)
    if not hwnd:
        return {"ok": False, "error": f"no visible window matching {pattern!r}"}
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    # Windows only lets the process that got the last input change the foreground: a lone Alt press gives us that
    for _ in range(5):
        keys("alt")
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.3)
        if user32.GetForegroundWindow() == hwnd:
            return {"ok": True, "window": describe(hwnd)}
    return {"ok": False, "error": "SetForegroundWindow refused", "foreground": describe(user32.GetForegroundWindow())}


def grab(x, y, w, h, out):
    from PIL import ImageGrab
    img = ImageGrab.grab(bbox=(int(x), int(y), int(x) + int(w), int(y) + int(h)), all_screens=True)
    img.save(out)
    return {"saved": out, "size": list(img.size)}


def diff(a, b):
    from PIL import Image, ImageChops, ImageStat
    ia, ib = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
    if ia.size != ib.size:
        return {"error": f"sizes differ {ia.size} {ib.size}"}
    mean = sum(ImageStat.Stat(ImageChops.difference(ia, ib)).mean) / 3
    return {"mean": round(mean, 2)}


def main():
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # real pixels, like the overlay window
    cmd, args = sys.argv[1], sys.argv[2:]
    result = {"state": state, "focus": focus, "keys": keys, "grab": grab, "diff": diff}[cmd](*args)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
