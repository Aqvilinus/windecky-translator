"""Pause Game While Translating on Windows: suspend the game's processes, resume them on dismiss.

Upstream sends SIGSTOP/SIGCONT to the game's process tree (found by Steam AppId in /proc). Here the game is the process
of the window the screenshot came from, if Steam started it (winport.hotkey.is_steam_game), and NtSuspendProcess /
NtResumeProcess (what Process Explorer's Suspend uses) pause it and its child processes. main.py pauses when the
translation of a game appears on screen and resumes everything when it is hidden.

The pids are also written to %TEMP%/decky-translator/suspended.json with their creation times, so a plugin restart
that happens while a game is paused (reload, Decky crash and restart) resumes it on start instead of leaving it
frozen; the creation time makes sure a pid that now belongs to another process (after a reboot) is left alone.
"""
import ctypes
import json
import logging
import os
from ctypes import wintypes
from typing import Dict, List, Optional

from .hotkey import STEAM_PROCESSES, processes, is_steam_game, process_created

logger = logging.getLogger(__name__)

ntdll = ctypes.WinDLL("ntdll")
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
ntdll.NtSuspendProcess.argtypes = [wintypes.HANDLE]
ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

PROCESS_SUSPEND_RESUME = 0x0800

STATE_FILE = os.path.join(os.environ.get("TEMP", "."), "decky-translator", "suspended.json")

# game pid -> [pid, creation time, exe name] suspended for it (the game and its children), in suspend order
_suspended: Dict[int, List[list]] = {}

RESUME_TRIES = 3


def game_pid(hwnd: Optional[int]) -> int:
    """The pid of the window's process if Steam started it, else 0."""
    if not hwnd:
        return 0
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value if pid.value and pid.value != os.getpid() and is_steam_game(pid.value) else 0


def _tree(pid: int) -> List[int]:
    """pid and its descendants (started after their parent: a stale parent pid doesn't count), except Steam's own
    processes and this one."""
    procs = processes()
    created = {}

    def when(p):
        if p not in created:
            created[p] = process_created(p)
        return created[p]

    children: Dict[int, List[int]] = {}
    for p, (parent, _) in procs.items():
        children.setdefault(parent, []).append(p)
    out, todo = [], [pid]
    while todo:
        p = todo.pop()
        if p in out or p == os.getpid() or (procs.get(p, (0, ""))[1] in STEAM_PROCESSES):
            continue
        out.append(p)
        for c in children.get(p, []):
            if when(c) is None or when(p) is None or when(c) >= when(p):
                todo.append(c)
    return out


def _call(fn, pid: int) -> bool:
    handle = kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
    if not handle:
        return False
    try:
        return fn(handle) == 0  # NTSTATUS STATUS_SUCCESS
    finally:
        kernel32.CloseHandle(handle)


def _save() -> None:
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_suspended, f)
        os.replace(tmp, STATE_FILE)
    except OSError as e:
        logger.warning(f"Could not save the paused game list: {e}")


def suspend(pid: int) -> bool:
    """Pause a game started by Steam (anything else is refused) and its child processes."""
    if not pid or pid in _suspended:
        return bool(pid)
    if pid == os.getpid() or not is_steam_game(pid):
        logger.warning(f"Not pausing process {pid}: not a game started by Steam")
        return False
    procs = processes()
    done = [[p, process_created(p) or 0, procs.get(p, (0, ""))[1]]
            for p in _tree(pid) if _call(ntdll.NtSuspendProcess, p)]
    if not done:
        logger.error(f"Could not pause process {pid}")
        return False
    _suspended[pid] = done
    _save()
    logger.info(f"Paused game {pid} ({len(done)} processes)")
    return True


def _same_process(p: int, created: int, exe: str, procs) -> bool:
    """Is pid p still the process that was suspended? By creation time; if that was unknown, by exe name."""
    now = process_created(p)
    if created:
        return now == created
    return now is not None and bool(exe) and procs.get(p, (0, ""))[1] == exe


def _resume_list(pids, check_identity: bool) -> list:
    """Resume the entries (last suspended first); returns those that are still suspended after a few tries.
    check_identity: the list comes from an earlier run, so skip pids that now belong to another process."""
    procs = processes() if check_identity else {}
    failed = []
    for entry in reversed(pids):
        if isinstance(entry, int):
            entry = [entry, 0, ""]
        p, created = int(entry[0]), int(entry[1])
        exe = entry[2] if len(entry) > 2 else ""
        if check_identity and not _same_process(p, created, exe, procs):
            continue  # gone, or the pid now belongs to another process
        for _ in range(RESUME_TRIES):
            if _call(ntdll.NtResumeProcess, p):
                break
            if process_created(p) is None:
                break  # exited: nothing left to resume
        else:
            logger.error(f"Could not resume process {p} (error {ctypes.get_last_error()})")
            failed.append(entry)
    failed.reverse()  # back to suspend order
    return failed


def resume(pid: int) -> bool:
    """Resume a paused game. A process that refuses stays listed (and in the state file), so the next resume or the
    next plugin start tries again instead of leaving it frozen."""
    pids = _suspended.pop(pid, None)
    if pids is None:
        return False
    failed = _resume_list(pids, check_identity=False)
    if failed:
        _suspended[pid] = failed
    _save()
    if failed:
        logger.error(f"Game {pid} is still partly paused ({len(failed)} processes)")
        return False
    logger.info(f"Resumed game {pid}")
    return True


def is_suspended(pid: int) -> bool:
    return pid in _suspended


def any_suspended() -> bool:
    return bool(_suspended)


def resume_all() -> None:
    for pid in list(_suspended):
        resume(pid)


def resume_leftovers() -> None:
    """On start: resume what a previous run of the plugin left paused (only processes that are still the same)."""
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            left = {int(k): v for k, v in json.load(f).items()}
    except (OSError, ValueError, TypeError, AttributeError):
        return
    _suspended.clear()
    for game, pids in left.items():
        try:
            failed = _resume_list(pids, check_identity=True)
        except (TypeError, ValueError, IndexError) as e:
            logger.warning(f"Skipped a damaged paused-game entry: {e}")
            continue
        if failed:
            _suspended[game] = failed
            logger.error(f"Game {game}, left paused by an earlier run, is still partly paused")
        else:
            logger.warning(f"Resumed game {game}, left paused by an earlier run")
    _save()
