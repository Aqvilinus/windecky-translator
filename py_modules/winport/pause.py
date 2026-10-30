"""Pause Game While Translating on Windows: suspend the game's processes, resume them when the translation is hidden.

Upstream sends SIGSTOP/SIGCONT to the game's process tree, found by the AppId on the command line of Steam's reaper
process. On Windows the game is the process of the captured window if Steam launched it: Steam puts the game's id into
the environment of every process it starts (SteamGameId, SteamAppId), and children keep it after a launcher exits.
psutil reads it and suspends and resumes the processes (NtSuspendProcess / NtResumeProcess, as Process Explorer does).

The paused processes are written to %TEMP%/decky-translator/suspended.json with their creation times, so a plugin
restart while a game is paused (reload, Decky crash) resumes it on start; the creation time makes sure a pid that now
belongs to another process is left alone.
"""
import ctypes
import json
import logging
import os
from ctypes import wintypes
from typing import Dict, List

import psutil

logger = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

STATE_FILE = os.path.join(os.environ.get("TEMP", "."), "decky-translator", "suspended.json")
RESUME_TRIES = 3

# game pid -> [[pid, creation time], ...] suspended for it (the game and its children), in suspend order
_suspended: Dict[int, List[list]] = {}


def steam_game_id(proc: psutil.Process) -> str:
    """The Steam game id in the process's environment ("" if Steam didn't launch it or it can't be read)."""
    try:
        env = proc.environ()  # keys upper-cased on Windows
    except psutil.Error:
        return ""
    game_id = env.get("STEAMGAMEID") or env.get("STEAMAPPID") or ""
    return "" if game_id == "0" else game_id


def game_pid(hwnd) -> int:
    """The pid of the window's process if Steam launched it, else 0."""
    if not hwnd:
        return 0
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value or pid.value == os.getpid():
        return 0
    try:
        return pid.value if steam_game_id(psutil.Process(pid.value)) else 0
    except psutil.Error:
        return 0


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
    """Pause the game game_pid() found, and its child processes."""
    if not pid or pid in _suspended:
        return bool(pid)
    try:
        game = psutil.Process(pid)
        procs = [game] + game.children(recursive=True)
    except psutil.Error as e:
        logger.error(f"Could not pause process {pid}: {e!r}")
        return False
    done = []
    for p in procs:
        try:
            p.suspend()
            done.append([p.pid, p.create_time()])
        except psutil.Error:
            pass
    if not done:
        logger.error(f"Could not pause process {pid}")
        return False
    _suspended[pid] = done
    _save()
    logger.info(f"Paused game {pid} ({len(done)} processes)")
    return True


def _resume_entries(entries) -> list:
    """Resume the entries, last suspended first, if each pid still is the process that was suspended; returns those
    still suspended after a few tries."""
    failed = []
    for entry in reversed(entries):
        pid, created = int(entry[0]), float(entry[1])
        for _ in range(RESUME_TRIES):
            try:
                p = psutil.Process(pid)
                if abs(p.create_time() - created) > 1:
                    break  # the pid now belongs to another process
                p.resume()
                break
            except psutil.NoSuchProcess:
                break  # exited: nothing left to resume
            except psutil.Error:
                continue
        else:
            logger.error(f"Could not resume process {pid}")
            failed.append(entry)
    failed.reverse()  # back to suspend order
    return failed


def resume(pid: int) -> bool:
    """Resume a paused game. A process that refuses stays listed (and in the state file), so the next resume or the
    next plugin start tries again instead of leaving it frozen."""
    entries = _suspended.pop(pid, None)
    if entries is None:
        return False
    failed = _resume_entries(entries)
    if failed:
        _suspended[pid] = failed
    _save()
    if failed:
        logger.error(f"Game {pid} is still partly paused ({len(failed)} processes)")
        return False
    logger.info(f"Resumed game {pid}")
    return True


def any_suspended() -> bool:
    return bool(_suspended)


def resume_all() -> None:
    for pid in list(_suspended):
        resume(pid)


def resume_leftovers() -> None:
    """On start: resume what a previous run of the plugin left paused."""
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            left = {int(k): v for k, v in json.load(f).items()}
    except (OSError, ValueError, TypeError, AttributeError):
        return
    _suspended.clear()
    for game, entries in left.items():
        try:
            failed = _resume_entries(entries)
        except (TypeError, ValueError, IndexError) as e:
            logger.warning(f"Skipped a damaged paused-game entry: {e}")
            continue
        if failed:
            _suspended[game] = failed
            logger.error(f"Game {game}, left paused by an earlier run, is still partly paused")
        else:
            logger.warning(f"Resumed game {game}, left paused by an earlier run")
    _save()
