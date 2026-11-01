"""Pause Game While Translating: the game's processes stay suspended while its translation is on screen.

Steam puts the game's id into the environment of every process it starts, and a launcher's children keep it: that is
how the game is told from any other window. The suspended processes are written to a state file with their creation
times, so a plugin that died while a game was paused resumes it on its next start, and leaves alone a pid that another
process got meanwhile."""
import ctypes
import json
import logging
import os
from ctypes import wintypes

import psutil

logger = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

STATE_FILE = os.path.join(os.environ.get("TEMP", "."), "decky-translator", "suspended.json")

_suspended = []  # [pid, creation time] in suspend order


class SuspendError(Exception):
    """Why the game keeps running; shown to the user."""


def suspend(hwnd):
    if _suspended:
        return
    game = _steam_game(hwnd)
    for p in [game, *game.children(recursive=True)]:
        try:
            p.suspend()
            _suspended.append([p.pid, p.create_time()])
        except psutil.Error as e:  # e.g. an anti-cheat helper that refuses: the rest still pauses
            logger.warning(f"Could not suspend process {p.pid}: {e!r}")
    if not _suspended:
        raise SuspendError("Windows didn't let the plugin pause this game (details in the plugin log)")
    _save()
    logger.info(f"Paused game {game.pid} ({len(_suspended)} processes)")


def is_suspended():
    return bool(_suspended)


def resume_all():
    if not _suspended:
        return
    _resume(_suspended)
    _suspended.clear()
    _save()
    logger.info("Resumed the game")


def resume_after_restart():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            left = json.load(f)
    except (OSError, ValueError):
        return
    if left:
        _resume(left)
        logger.warning(f"Resumed {len(left)} processes an earlier run left paused")
    _save()


def _steam_game(hwnd):
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        process = psutil.Process(pid.value)
        env = process.environ()  # keys upper-cased on Windows
    except psutil.AccessDenied:
        raise SuspendError("Windows didn't let the plugin look into the game's process "
                           "(is the game running as administrator?)") from None
    except psutil.NoSuchProcess:
        raise SuspendError("the game window is gone") from None
    game_id = env.get("STEAMGAMEID") or env.get("STEAMAPPID") or ""
    if game_id in ("", "0"):
        raise SuspendError("this window isn't a game Steam started, so it keeps running")
    return process


def _resume(entries):
    for pid, created in reversed(entries):
        try:
            p = psutil.Process(pid)
            if abs(p.create_time() - created) <= 1:  # else the pid now belongs to another process
                p.resume()
        except psutil.NoSuchProcess:
            pass
        except psutil.Error as e:
            logger.error(f"Could not resume process {pid}: {e!r}")


def _save():
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(_suspended, f)
