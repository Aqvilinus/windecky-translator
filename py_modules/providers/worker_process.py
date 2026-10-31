# providers/worker_process.py
# A worker subprocess on the bundled Python (python_runtime.py) that answers each JSON line on its stdin with one JSON
# line on its stdout: the Chrome Screen AI OCR worker and the offline NLLB translation worker.

import json
import logging
import os
import queue
import subprocess
import threading
from typing import Optional

from . import python_runtime

logger = logging.getLogger(__name__)


class JsonLineWorker:
    """Start, ask, stop. A reader thread puts the worker's reply lines in a queue, so request() can give up after a
    timeout (select() can't wait on pipes on Windows). A worker that times out or answers garbage is killed: its
    late reply would otherwise answer the next request. Safe to use from several threads."""

    def __init__(self, name: str, script: str, args=(), env: Optional[dict] = None):
        self.name = name
        self._cmd_tail = ["-S", script, *args]
        self._env = env or {}
        self._proc: Optional[subprocess.Popen] = None
        self._replies: "queue.Queue[Optional[bytes]]" = queue.Queue()
        self._lock = threading.RLock()

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, python_path: str, pythonpath: str, env: Optional[dict] = None) -> bool:
        """Start the worker if it isn't running; False if it can't be started. env: more variables for this run."""
        with self._lock:
            if self.alive:
                return True
            env = {**os.environ, "PYTHONPATH": pythonpath, "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
                   **self._env, **(env or {})}
            env = {k: v for k, v in env.items() if v is not None}  # None removes an inherited variable
            try:
                self._proc = subprocess.Popen([python_path, *self._cmd_tail], stdin=subprocess.PIPE,
                                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                                              **python_runtime.popen_kwargs())
            except OSError as e:
                logger.error(f"{self.name} worker could not start: {e}")
                self._proc = None
                return False
            self._replies = queue.Queue()
            threading.Thread(target=self._read_replies, args=(self._proc, self._replies), daemon=True).start()
            threading.Thread(target=self._log_stderr, args=(self._proc,), daemon=True).start()
            logger.info(f"{self.name} worker started")
            return True

    def request(self, message: dict, timeout: float) -> Optional[dict]:
        """Send one message and wait for the reply; None (and the worker stopped) if it doesn't come or is garbage."""
        with self._lock:
            if not self.alive:
                return None
            try:
                self._proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
                self._proc.stdin.flush()
                line = self._replies.get(timeout=timeout)
            except queue.Empty:
                logger.error(f"{self.name} worker: no answer in {timeout} s")
                self._kill()
                return None
            except OSError as e:  # the pipe broke: the worker is gone
                logger.error(f"{self.name} worker: {e}")
                self._kill()
                return None
            if not line:
                logger.error(f"{self.name} worker exited")
                self._kill()
                return None
            try:
                return json.loads(line.decode("utf-8"))
            except ValueError as e:
                logger.error(f"{self.name} worker: unreadable answer: {e}")
                self._kill()
                return None

    def stop(self, shutdown_message: Optional[dict] = None) -> None:
        """Ask the worker to exit (shutdown_message, then closing its stdin), and make sure it does."""
        with self._lock:
            proc, self._proc = self._proc, None
            if proc is None:
                return
            try:
                if proc.poll() is None:
                    if shutdown_message:
                        proc.stdin.write((json.dumps(shutdown_message) + "\n").encode("utf-8"))
                        proc.stdin.flush()
                    proc.stdin.close()
                    proc.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                proc.kill()
            logger.info(f"{self.name} worker stopped")

    def _kill(self) -> None:
        proc, self._proc = self._proc, None
        if proc and proc.poll() is None:
            proc.kill()

    @staticmethod
    def _read_replies(proc, replies) -> None:
        for line in iter(proc.stdout.readline, b""):
            replies.put(line)
        replies.put(None)  # end of output: the worker exited

    def _log_stderr(self, proc) -> None:
        for raw in iter(proc.stderr.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip()
            if line:
                logger.debug(f"{self.name} worker: {line}")
