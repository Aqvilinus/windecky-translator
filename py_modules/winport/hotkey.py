"""The translate shortcut on Windows: Ctrl+Alt+T as a system-wide hotkey, registered only while a game is in front.

XInput can't stand in for upstream's hidraw controller reading everywhere: on current Windows builds XInput (on
GameInput) gives button states only to the foreground app, and the plugin's backend never is. A keyboard shortcut
reaches the backend through RegisterHotKey whatever app is in front, and handheld vendor apps (OneXConsole) or Steam
Input can map any controller button to it.

"A game" is a window whose process Steam started (a descendant of steam.exe that isn't one of Steam's own processes):
Steam games, non-Steam shortcuts and emulators launched from the library. Many games start through a launcher that
exits once the game runs (anti-cheat bootstrappers, game.exe -> game_x64.exe), which cuts the chain to steam.exe; such a
process still counts while Steam reports a running app (set_steam_app, from the frontend's app lifetime notifications)
and it was started after that app. Everywhere else (Big Picture, the desktop, a browser) the combo is not registered
and keeps its normal meaning there.

A WinEvent hook (EVENT_SYSTEM_FOREGROUND, out of context) reports foreground changes; the hook, the hotkey and the
message loop share one thread that sleeps in GetMessage: no polling, no CPU while idle.
"""
import ctypes
import logging
import os
import threading
from ctypes import wintypes

logger = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WINEVENTPROC = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND, wintypes.LONG,
                                  wintypes.LONG, wintypes.DWORD, wintypes.DWORD)
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SetWinEventHook.restype = wintypes.HANDLE
user32.SetWinEventHook.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, WINEVENTPROC, wintypes.DWORD,
                                   wintypes.DWORD, wintypes.DWORD]
user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
kernel32.GetSystemTimeAsFileTime.argtypes = [ctypes.POINTER(wintypes.FILETIME)]

WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
WM_APP_EVALUATE = 0x8001  # WM_APP + 1: re-check whether the hotkey should be registered
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
HOTKEY_ID = 1
HOTKEY = (MOD_CONTROL | MOD_ALT, ord("T"), "Ctrl+Alt+T")
EVENT_SYSTEM_FOREGROUND = 0x0003
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE = wintypes.HANDLE(-1).value
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
FILETIME_SECOND = 10_000_000  # FILETIME ticks are 100 ns
# a game process may start a little before Steam reports its app as running
APP_START_MARGIN = 120 * FILETIME_SECOND

# Steam's own processes are not games, though steam.exe starts them
STEAM_PROCESSES = {"steam.exe", "steamwebhelper.exe", "gameoverlayui.exe", "gameoverlayui64.exe",
                   "steamerrorreporter.exe", "steamerrorreporter64.exe", "steamservice.exe", "steamsysinfo.exe"}


# Steam apps running now (frontend: SteamClient.GameSessions.RegisterForAppLifetimeNotifications):
# appid -> (FILETIME the app was reported running, 0 if it already ran when the plugin started; Steam's instance id)
_steam_apps = {}


def _filetime_int(ft):
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


def now_filetime():
    ft = wintypes.FILETIME()
    kernel32.GetSystemTimeAsFileTime(ctypes.byref(ft))
    return _filetime_int(ft)


def process_created(pid):
    """Creation time of the process (FILETIME as int), or None if it can't be opened (gone, protected)."""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            return None
        return _filetime_int(times[0])
    finally:
        kernel32.CloseHandle(handle)


def set_steam_app(appid, running, instance_id=0, already_running=False):
    """Steam reports an app started or stopped."""
    if running:
        _steam_apps[int(appid)] = (0 if already_running else now_filetime(), int(instance_id or 0))
    else:
        _steam_apps.pop(int(appid), None)
    logger.info("Steam app %s %s (instance %s)", appid, "running" if running else "stopped", instance_id)


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]


kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]


def processes():
    """{pid: (parent pid, exe name lower-case)} from a ToolHelp snapshot."""
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID_HANDLE:
        return {}
    out = {}
    try:
        e = PROCESSENTRY32W(dwSize=ctypes.sizeof(PROCESSENTRY32W))
        ok = kernel32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            out[e.th32ProcessID] = (e.th32ParentProcessID, e.szExeFile.lower())
            ok = kernel32.Process32NextW(snap, ctypes.byref(e))
    finally:
        kernel32.CloseHandle(snap)
    return out


def is_steam_game(pid, procs=None):
    """True if pid is a process Steam started (directly or through a launcher), other than Steam's own.

    Walks up the parent chain to steam.exe. A parent that is gone, or whose pid now belongs to a process newer than
    its child (pid reuse), cuts the chain: then the process counts if Steam reports a running app and the oldest
    process left of the chain started after that app (the launcher Steam started has exited)."""
    procs = procs if procs is not None else processes()
    entry = procs.get(pid)
    if not entry or entry[1] in STEAM_PROCESSES:
        return False
    apps = list(_steam_apps.values())  # a snapshot: the backend's event loop thread updates the dict
    instances = {inst for _, inst in apps if inst}
    seen = set()
    created = process_created(pid)
    while pid not in seen:
        seen.add(pid)
        if pid in instances:
            return True
        parent = entry[0]
        p = procs.get(parent)
        parent_created = process_created(parent) if p else None
        if p is None or (parent_created and created and parent_created > created):
            return _started_with_steam_app(entry[1], created, apps)
        if p[1] == "steam.exe":
            return True
        pid, entry, created = parent, p, parent_created
    return False


def _started_with_steam_app(root_exe, root_created, apps):
    """The process at the top of a cut chain: a game if a Steam app runs and the process started after it."""
    if not apps or root_exe in ("explorer.exe", "svchost.exe", "services.exe", "wininit.exe"):
        return False
    if not root_created:
        return False
    since = min(t for t, _ in apps)
    return since == 0 or root_created >= since - APP_START_MARGIN


class GameHotkey:
    def __init__(self, on_press):
        self._on_press = on_press
        self._tid = None
        self._ready = threading.Event()
        self._hook = None
        self._hook_proc = WINEVENTPROC(self._on_foreground)  # keep a reference while hooked
        self.active = False
        self.error = None
        self.foreground = None
        self._holds = set()  # reasons to keep the hotkey whatever is in front: "pause", "overlay"
        self._enabled = True  # the plugin's on/off switch: off, the combo is never taken
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

    def _evaluate(self):
        pid = wintypes.DWORD(0)
        hwnd = user32.GetForegroundWindow()
        if hwnd:
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        procs = processes()
        game = bool(pid.value) and pid.value != os.getpid() and is_steam_game(pid.value, procs)
        self.foreground = (pid.value, (procs.get(pid.value) or (0, ""))[1], game)
        self._set_registered(self._enabled and (game or bool(self._holds)))

    def _on_foreground(self, *_):
        try:
            self._evaluate()
        except Exception as e:  # noqa: BLE001 - never raise into the hook
            logger.error("foreground check failed: %r", e)

    def _run(self):
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # create this thread's message queue
        self._tid = threading.get_native_id()
        self._hook = user32.SetWinEventHook(EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND, None, self._hook_proc,
                                            0, 0, 0)  # WINEVENT_OUTOFCONTEXT
        self._on_foreground()
        self._ready.set()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_APP_EVALUATE:
                self._on_foreground()
            elif msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                try:
                    self._on_press()
                except Exception as e:  # noqa: BLE001 - never kill the loop
                    logger.error("hotkey handler failed: %r", e)
        if self._hook:
            user32.UnhookWinEvent(self._hook)
            self._hook = None
        self._set_registered(False)

    # ---- other threads
    def status(self):
        return {"hotkey": HOTKEY[2], "registered": self.active, "error": self.error, "foreground": self.foreground}

    def hold(self, on, reason="pause"):
        """Keep the hotkey registered whatever is in front, for a reason:
        "pause": the game is paused, and Windows may show a 'Not responding' ghost window instead of it, which
        isn't a Steam game; "overlay": a translation is on screen and the shortcut must close it, also when it
        was started from the side menu over Big Picture or another app that isn't a Steam game."""
        if on:
            self._holds.add(reason)
        else:
            self._holds.discard(reason)
        self.refresh()

    def set_enabled(self, on):
        """The plugin was switched on or off: off, Ctrl+Alt+T keeps its normal meaning in games too."""
        self._enabled = bool(on)
        self.refresh()

    def refresh(self):
        """Re-check the foreground window (e.g. Steam just reported a game as running)."""
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_APP_EVALUATE, 0, 0)

    def close(self):
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            self._thread.join(2)
