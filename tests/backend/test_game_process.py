"""Pause Game While Translating (py_modules/game_process.py), with psutil's processes replaced by fakes."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

if sys.platform != "win32":
    raise unittest.SkipTest("Windows-only")

import psutil  # noqa: E402

import game_process  # noqa: E402

GAME, CHILD, BROWSER = 100, 101, 200


class FakeProcess:
    def __init__(self, world, pid):
        if pid not in world.procs:
            raise psutil.NoSuchProcess(pid)
        self.world, self.pid = world, pid

    def environ(self):
        return dict(self.world.procs[self.pid]["env"])

    def children(self, recursive=False):
        return [FakeProcess(self.world, p) for p, info in self.world.procs.items() if info.get("parent") == self.pid]

    def create_time(self):
        return self.world.procs[self.pid]["created"]

    def suspend(self):
        if self.pid in self.world.refuse:
            raise psutil.AccessDenied(self.pid)
        self.world.log.append(("suspend", self.pid))

    def resume(self):
        self.world.log.append(("resume", self.pid))


class GameProcessTests(unittest.TestCase):
    def setUp(self):
        self.procs = {
            GAME: {"env": {"STEAMGAMEID": "237990", "STEAMAPPID": "237990"}, "created": 1000.0},
            CHILD: {"env": {"STEAMGAMEID": "237990"}, "created": 1001.0, "parent": GAME},
            BROWSER: {"env": {"PATH": "x"}, "created": 900.0},
        }
        self.refuse = set()
        self.log = []
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for p in (mock.patch.object(game_process, "STATE_FILE", os.path.join(tmp.name, "suspended.json")),
                  mock.patch.object(game_process.psutil, "Process", lambda pid: FakeProcess(self, pid)),
                  mock.patch.object(game_process, "_suspended", [])):
            p.start()
            self.addCleanup(p.stop)

    def window_of(self, pid):
        def get_pid(hwnd, out):
            out._obj.value = pid
        return mock.patch.object(game_process.user32, "GetWindowThreadProcessId", get_pid)

    def saved(self):
        with open(game_process.STATE_FILE, encoding="utf-8") as f:
            return json.load(f)

    def test_only_a_process_steam_launched_is_a_game(self):
        with self.window_of(BROWSER), self.assertRaises(game_process.SuspendError):
            game_process.suspend(1)
        self.procs[BROWSER]["env"]["STEAMAPPID"] = ""  # Steam's own processes have it empty
        with self.window_of(BROWSER), self.assertRaises(game_process.SuspendError):
            game_process.suspend(1)
        self.assertEqual(self.log, [])

    def test_suspend_the_game_and_its_children(self):
        with self.window_of(GAME):
            game_process.suspend(1)
        self.assertEqual(self.log, [("suspend", GAME), ("suspend", CHILD)])
        self.assertEqual(self.saved(), [[GAME, 1000.0], [CHILD, 1001.0]])

    def test_a_game_windows_refuses_to_suspend(self):
        self.refuse = {GAME, CHILD}
        with self.window_of(GAME), self.assertRaises(game_process.SuspendError):
            game_process.suspend(1)
        self.assertFalse(game_process.is_suspended())

    def test_resume_in_reverse_order(self):
        with self.window_of(GAME):
            game_process.suspend(1)
        game_process.resume_all()
        self.assertEqual(self.log[2:], [("resume", CHILD), ("resume", GAME)])
        self.assertFalse(game_process.is_suspended())
        self.assertEqual(self.saved(), [])

    def test_an_exited_process_is_skipped(self):
        with self.window_of(GAME):
            game_process.suspend(1)
        del self.procs[CHILD]
        game_process.resume_all()
        self.assertEqual(self.log[2:], [("resume", GAME)])

    def test_after_a_restart_only_the_same_processes_are_resumed(self):
        with open(game_process.STATE_FILE, "w", encoding="utf-8") as f:
            json.dump([[GAME, 1000.0], [CHILD, 999.0]], f)  # CHILD's pid was reused
        game_process.resume_after_restart()
        self.assertEqual(self.log, [("resume", GAME)])
        self.assertEqual(self.saved(), [])


if __name__ == "__main__":
    unittest.main()
