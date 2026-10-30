"""Pause Game While Translating (py_modules/winport/pause.py), with psutil's processes replaced by fakes."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

if sys.platform != "win32":
    raise unittest.SkipTest("winport is Windows-only")

import psutil  # noqa: E402

from winport import pause  # noqa: E402

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
        self.world.log.append(("suspend", self.pid))

    def resume(self):
        if self.pid in self.world.refuse_resume:
            raise psutil.AccessDenied(self.pid)
        self.world.log.append(("resume", self.pid))


class PauseTests(unittest.TestCase):
    def setUp(self):
        self.procs = {
            GAME: {"env": {"STEAMGAMEID": "237990", "STEAMAPPID": "237990"}, "created": 1000.0},
            CHILD: {"env": {"STEAMGAMEID": "237990"}, "created": 1001.0, "parent": GAME},
            BROWSER: {"env": {"PATH": "x"}, "created": 900.0},
        }
        self.refuse_resume = set()
        self.log = []
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for p in (mock.patch.object(pause, "STATE_FILE", os.path.join(tmp.name, "suspended.json")),
                  mock.patch.object(pause.psutil, "Process", lambda pid: FakeProcess(self, pid)),
                  mock.patch.dict(pause._suspended, clear=True)):
            p.start()
            self.addCleanup(p.stop)

    def window_of(self, pid):
        def get_pid(hwnd, out):
            out._obj.value = pid
        return mock.patch.object(pause.user32, "GetWindowThreadProcessId", get_pid)

    def saved(self):
        with open(pause.STATE_FILE, encoding="utf-8") as f:
            return json.load(f)

    def test_only_a_process_steam_launched_is_a_game(self):
        with self.window_of(GAME):
            self.assertEqual(pause.game_pid(1), GAME)
        with self.window_of(BROWSER):
            self.assertEqual(pause.game_pid(1), 0)
        self.procs[BROWSER]["env"]["STEAMAPPID"] = ""  # Steam's own processes have it empty
        with self.window_of(BROWSER):
            self.assertEqual(pause.game_pid(1), 0)

    def test_suspend_the_game_and_its_children(self):
        self.assertTrue(pause.suspend(GAME))
        self.assertEqual(self.log, [("suspend", GAME), ("suspend", CHILD)])
        self.assertEqual(self.saved(), {str(GAME): [[GAME, 1000.0], [CHILD, 1001.0]]})

    def test_resume_in_reverse_order(self):
        pause.suspend(GAME)
        self.assertTrue(pause.resume(GAME))
        self.assertEqual(self.log[2:], [("resume", CHILD), ("resume", GAME)])
        self.assertFalse(pause.any_suspended())
        self.assertEqual(self.saved(), {})

    def test_failed_resume_stays_listed_for_a_retry(self):
        pause.suspend(GAME)
        self.refuse_resume = {CHILD}
        self.assertFalse(pause.resume(GAME))
        self.assertEqual(self.saved(), {str(GAME): [[CHILD, 1001.0]]})
        self.refuse_resume = set()
        pause.resume_all()
        self.assertFalse(pause.any_suspended())

    def test_exited_process_is_not_a_failure(self):
        pause.suspend(GAME)
        del self.procs[CHILD]
        self.assertTrue(pause.resume(GAME))

    def test_leftovers_resume_only_the_same_processes(self):
        state = {str(GAME): [[GAME, 1000.0], [CHILD, 999.0]]}  # CHILD's pid was reused
        with open(pause.STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f)
        pause.resume_leftovers()
        self.assertEqual(self.log, [("resume", GAME)])
        self.assertEqual(self.saved(), {})


if __name__ == "__main__":
    unittest.main()
