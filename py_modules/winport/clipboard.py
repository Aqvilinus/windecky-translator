"""Text on the Windows clipboard.

Steam's text fields in Big Picture have no Paste item in their right-click menu (and a gamepad has no Ctrl+V), so the
settings' key dialogs get a Paste button that reads the clipboard here.
"""
import ctypes
import time
from ctypes import wintypes

CF_UNICODETEXT = 13

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.CloseClipboard.restype = wintypes.BOOL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = wintypes.LPVOID
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalSize.restype = ctypes.c_size_t

MAX_CHARS = 4096  # an API key or a server address; more is not what the Paste button is for


def get_text() -> str:
    """The clipboard's text, "" when it holds none. Retries briefly while another app has the clipboard open."""
    for _ in range(10):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.02)
    else:
        return ""
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            # read no further than the block (its text should end in a NUL, but nothing guarantees it)
            chars = min(kernel32.GlobalSize(handle) // ctypes.sizeof(ctypes.c_wchar), MAX_CHARS)
            return ctypes.wstring_at(ptr, chars).split("\0", 1)[0]
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()
