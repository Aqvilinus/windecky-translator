"""Which processes are Steam games, for Pause Game While Translating (process.py).

A game is a process Steam started (a descendant of steam.exe that isn't one of Steam's own processes): Steam games,
non-Steam shortcuts and emulators launched from the library. Many games start through a launcher that exits once the
game runs (anti-cheat bootstrappers, game.exe -> game_x64.exe), which cuts the chain to steam.exe; such a process still
counts while Steam reports a running app (set_steam_app, from the frontend's app lifetime notifications, src/windows.ts)
and it was started after that app.
"""
import ctypes
import logging
from ctypes import wintypes

logger = logging.getLogger(__name__)

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
kernel32.GetSystemTimeAsFileTime.argtypes = [ctypes.POINTER(wintypes.FILETIME)]

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
