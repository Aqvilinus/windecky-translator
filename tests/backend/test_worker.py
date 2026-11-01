"""providers/worker.py Worker against a small worker script on this test's own Python."""
import sys
import textwrap

import pytest

from providers import worker as worker_module
from providers.worker import Worker


@pytest.fixture(autouse=True)
def this_python(monkeypatch):
    monkeypatch.setattr(worker_module, "PYTHON_EXE", sys.executable)

WORKER = textwrap.dedent('''
    import json, os, sys, time
    for line in sys.stdin:
        msg = json.loads(line)
        if msg["cmd"] == "echo":
            print(json.dumps({"ok": True, "text": msg["text"], "env": os.environ.get("TEST_VAR")}), flush=True)
        elif msg["cmd"] == "sleep":
            time.sleep(5)
        elif msg["cmd"] == "garbage":
            print("not json", flush=True)
        elif msg["cmd"] == "shutdown":
            break
''')


def worker(tmp_path, **kw):
    script = tmp_path / "worker.py"
    script.write_text(WORKER, encoding="utf-8")
    w = Worker("test", str(script), **kw)
    assert w.start(env={"TEST_VAR": "on"})
    return w


def test_request_and_stop(tmp_path):
    w = worker(tmp_path)
    assert w.request({"cmd": "echo", "text": "hi"}, timeout=10) == {"ok": True, "text": "hi", "env": "on"}
    w.stop({"cmd": "shutdown"})
    assert not w.alive
    assert w.request({"cmd": "echo", "text": "hi"}, timeout=1) is None


def test_a_worker_that_doesnt_answer_in_time_is_stopped(tmp_path):
    w = worker(tmp_path)
    assert w.request({"cmd": "sleep"}, timeout=0.3) is None
    assert not w.alive  # its late answer must not reach the next request
    assert w.start()
    assert w.request({"cmd": "echo", "text": "again"}, timeout=10)["text"] == "again"
    w.stop()


def test_a_garbage_answer_stops_the_worker(tmp_path):
    w = worker(tmp_path)
    assert w.request({"cmd": "garbage"}, timeout=10) is None
    assert not w.alive
