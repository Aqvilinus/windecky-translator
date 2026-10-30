"""Pause Game While Translating bookkeeping (py_modules/winport/process.py), with the Win32 calls replaced."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

import _paths  # noqa: F401

if sys.platform != "win32":
    raise unittest.SkipTest("winport is Windows-only")

from winport import process  # noqa: E402

GAME, CHILD = 100, 101
PROCS = {GAME: (1, "game.exe"), CHILD: (GAME, "helper.exe")}
CREATED = {GAME: 1000, CHILD: 1001}


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.created = dict(CREATED)
        self.refuse_resume = set()
        self.resumed = []
        patches = [
            mock.patch.object(process, "STATE_FILE", os.path.join(self.tmp.name, "suspended.json")),
            mock.patch.object(process, "processes", lambda: dict(PROCS)),
            mock.patch.object(process, "process_created", lambda p: self.created.get(p)),
            mock.patch.object(process, "is_steam_game", lambda p: p == GAME),
            mock.patch.object(process, "_tree", lambda p: [GAME, CHILD]),
            mock.patch.object(process, "_call", self._call),
            mock.patch.dict(process._suspended, clear=True),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _call(self, fn, pid):
        if fn is process.ntdll.NtResumeProcess:
            if pid in self.refuse_resume:
                return False
            self.resumed.append(pid)
        return True

    def saved(self):
        with open(process.STATE_FILE, encoding="utf-8") as f:
            return json.load(f)

    def test_suspend_records_creation_time_and_exe(self):
        self.assertTrue(process.suspend(GAME))
        self.assertEqual(self.saved(), {str(GAME): [[GAME, 1000, "game.exe"], [CHILD, 1001, "helper.exe"]]})

    def test_suspend_refuses_non_games(self):
        self.assertFalse(process.suspend(555))
        self.assertFalse(process.any_suspended())

    def test_resume_in_reverse_order(self):
        process.suspend(GAME)
        self.assertTrue(process.resume(GAME))
        self.assertEqual(self.resumed, [CHILD, GAME])
        self.assertFalse(process.any_suspended())
        self.assertEqual(self.saved(), {})

    def test_failed_resume_stays_listed_for_a_retry(self):
        process.suspend(GAME)
        self.refuse_resume = {CHILD}
        self.assertFalse(process.resume(GAME))
        self.assertTrue(process.is_suspended(GAME))
        self.assertEqual(self.saved(), {str(GAME): [[CHILD, 1001, "helper.exe"]]})
        self.refuse_resume = set()
        process.resume_all()
        self.assertFalse(process.any_suspended())
        self.assertEqual(self.saved(), {})

    def test_exited_process_is_not_a_failure(self):
        process.suspend(GAME)
        self.refuse_resume = {CHILD}
        del self.created[CHILD]  # gone: OpenProcess fails, nothing to resume
        self.assertTrue(process.resume(GAME))

    def test_leftovers_resume_only_the_same_processes(self):
        state = {str(GAME): [[GAME, 1000, "game.exe"], [CHILD, 999, "helper.exe"]], "7": [[7, 0, "game.exe"]]}
        with open(process.STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f)
        PROCS_7 = {**PROCS, 7: (1, "game.exe")}
        self.created[7] = 5
        with mock.patch.object(process, "processes", lambda: PROCS_7):
            process.resume_leftovers()
        # CHILD's creation time changed (pid reused); pid 7 had no creation time but the same exe name
        self.assertEqual(sorted(self.resumed), [7, GAME])
        self.assertEqual(self.saved(), {})

    def test_leftovers_old_format(self):
        with open(process.STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({str(GAME): [[GAME, 1000], [CHILD, 1001]]}, f)
        process.resume_leftovers()
        self.assertEqual(self.resumed, [CHILD, GAME])


if __name__ == "__main__":
    unittest.main()
