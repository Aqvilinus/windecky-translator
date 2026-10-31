# Local OCR via Chrome Screen AI. The DLL and TFLite models are
# fetched on demand from Google's CIPD server, not bundled in the plugin.

import asyncio
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
from typing import List, Optional

from .base import OCRError, OCRProvider, ProviderType, TextRegion
from . import python_runtime

logger = logging.getLogger(__name__)

DEFAULT_MIN_CONFIDENCE = 0.5
OCR_TIMEOUT_SECONDS = 120
WORKER_READY_TIMEOUT_SECONDS = 60

_WORKER_ENV_STRIP = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


class ChromeScreenAIProvider(OCRProvider):
    """OCR provider backed by chrome_screen_ai.dll. Oneshot subprocess by
    default; persistent worker is opt-in for lower per-call latency."""

    # Engine auto-detects across 77+ scripts; we just advertise what the
    # rest of the plugin supports plus 'auto'.
    SUPPORTED_LANGUAGES = [
        'auto', 'ar', 'bg', 'zh-CN', 'zh-TW', 'hr', 'cs', 'da', 'nl', 'no', 'en',
        'fi', 'fr', 'de', 'el', 'hi', 'hu', 'it', 'ja', 'ko', 'pl', 'pt',
        'ro', 'ru', 'es', 'sv', 'th', 'tr', 'uk', 'vi',
    ]

    def __init__(
        self,
        plugin_dir: str = "",
        model_dir: str = "",
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    ):
        self._plugin_dir = plugin_dir or os.environ.get("DECKY_PLUGIN_DIR", python_runtime.PLUGIN_DIR)
        # model_dir holds the DLL and TFLite files; owned by ScreenAIDownloader.
        self._model_dir = model_dir
        self._min_confidence = max(0.0, min(1.0, min_confidence))
        self._init_error: Optional[str] = None
        self._python_path: Optional[str] = None

        self._persistent_mode = False
        self._worker_proc: Optional[subprocess.Popen] = None
        self._worker_lock = threading.Lock()

        # Prefer the extracted bin/py_modules copy (Decky Store install),
        # fall back to root py_modules in dev.
        bin_script = os.path.join(
            self._plugin_dir, "bin", "py_modules", "providers",
            "chromescreenai_subprocess.py",
        )
        root_script = os.path.join(
            self._plugin_dir, "py_modules", "providers",
            "chromescreenai_subprocess.py",
        )
        self._subprocess_script = bin_script if os.path.exists(bin_script) else root_script

        self._py_modules_dir = python_runtime.worker_pythonpath(self._plugin_dir)

        logger.debug(
            f"ChromeScreenAIProvider initialized "
            f"(model_dir={self._model_dir}, min_confidence={min_confidence})"
        )

    @property
    def name(self) -> str:
        return "Chrome Screen AI (Local)"

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.CHROME_SCREEN_AI

    def set_model_dir(self, model_dir: str) -> None:
        if model_dir == self._model_dir:
            return
        self._model_dir = model_dir
        # Worker holds an open DLL handle from the old path; restart it.
        if self._is_worker_alive():
            self.stop_worker()
            if self._persistent_mode:
                threading.Thread(target=self._warmup_worker, daemon=True).start()

    def set_min_confidence(self, value: float) -> None:
        v = max(0.0, min(1.0, value))
        if v == self._min_confidence:
            return
        self._min_confidence = v
        # Filtering is set in the worker init payload; restart to apply.
        if self._is_worker_alive():
            self.stop_worker()
            if self._persistent_mode:
                threading.Thread(target=self._warmup_worker, daemon=True).start()

    def _check_availability(self) -> bool:
        self._init_error = None

        if not os.path.exists(self._subprocess_script):
            self._init_error = (
                f"Chrome Screen AI subprocess script missing: {self._subprocess_script}"
            )
            logger.warning(self._init_error)
            return False

        so_path = os.path.join(self._model_dir or "", python_runtime.SCREENAI_LIBRARY)
        if not self._model_dir or not os.path.exists(so_path):
            self._init_error = "Chrome Screen AI engine not downloaded"
            return False

        self._python_path = python_runtime.find_python(self._plugin_dir)
        if not self._python_path:
            self._init_error = python_runtime.missing_message()
            logger.warning(self._init_error)
            return False

        return True

    def is_available(self, language: str = "auto") -> bool:
        if not self._check_availability():
            return False
        return language in self.SUPPORTED_LANGUAGES

    def get_supported_languages(self) -> List[str]:
        return self.SUPPORTED_LANGUAGES.copy()

    def get_init_error(self) -> Optional[str]:
        return self._init_error

    def set_persistent_mode(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._persistent_mode:
            return
        self._persistent_mode = enabled
        logger.info(f"Chrome Screen AI persistent mode: {enabled}")
        if enabled:
            threading.Thread(target=self._warmup_worker, daemon=True).start()
        else:
            self.stop_worker()

    def _warmup_worker(self) -> None:
        if self._persistent_mode:
            self.start_worker()

    def _is_worker_alive(self) -> bool:
        proc = self._worker_proc
        return proc is not None and proc.poll() is None

    def _start_stderr_drainer(self, proc: subprocess.Popen) -> None:
        def drain():
            try:
                stream = proc.stderr
                if stream is None:
                    return
                for raw in iter(stream.readline, b''):
                    if not raw:
                        break
                    try:
                        line = raw.decode('utf-8', errors='replace').rstrip()
                    except Exception:
                        continue
                    if line and re.match(r"[IW]\d{4} ", line):
                        logger.debug(f"ChromeScreenAI worker: {line}")
                    elif line:
                        logger.warning(f"ChromeScreenAI worker stderr: {line}")
            except Exception:
                pass

        threading.Thread(target=drain, daemon=True).start()

    def _build_worker_env(self) -> dict:
        env = os.environ.copy()
        env['PYTHONPATH'] = self._py_modules_dir
        env['PYTHONNOUSERSITE'] = '1'
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        for k in _WORKER_ENV_STRIP:
            env.pop(k, None)
        return env

    def start_worker(self) -> bool:
        with self._worker_lock:
            if not self._persistent_mode:
                return False
            if self._worker_proc is not None and self._worker_proc.poll() is None:
                return True

            if not self._check_availability() or not self._python_path:
                logger.warning("Cannot start Chrome Screen AI worker: not available")
                return False

            env = self._build_worker_env()
            try:
                self._worker_proc = subprocess.Popen(
                    [self._python_path, '-S', self._subprocess_script, '--worker'],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    **python_runtime.popen_kwargs(),
                )
            except Exception as e:
                logger.error(f"Failed to spawn Chrome Screen AI worker: {e}")
                self._worker_proc = None
                return False

            self._start_stderr_drainer(self._worker_proc)

            init_msg = {
                "type": "init",
                "model_dir": self._model_dir,
                "min_confidence": self._min_confidence,
            }
            start = time.time()
            try:
                self._worker_proc.stdin.write((json.dumps(init_msg) + "\n").encode())
                self._worker_proc.stdin.flush()
                ready_line = python_runtime.readline_with_timeout(self._worker_proc.stdout, WORKER_READY_TIMEOUT_SECONDS)
                if not ready_line:
                    logger.error("Chrome Screen AI worker died or hung before its ready response")
                    self._kill_worker_unlocked()
                    return False
                ready = json.loads(ready_line.decode().strip())
                if ready.get("error"):
                    logger.error(f"Chrome Screen AI worker init error: {ready['error']}")
                    self._kill_worker_unlocked()
                    return False
            except Exception as e:
                logger.error(f"Chrome Screen AI worker init failed: {e}")
                self._kill_worker_unlocked()
                return False

            elapsed = time.time() - start
            logger.info(f"Chrome Screen AI worker ready ({elapsed:.2f}s)")
            return True

    def stop_worker(self) -> None:
        with self._worker_lock:
            self._kill_worker_unlocked()

    def _kill_worker_unlocked(self) -> None:
        proc = self._worker_proc
        self._worker_proc = None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                try:
                    proc.stdin.write(b'{"type":"shutdown"}\n')
                    proc.stdin.flush()
                except Exception:
                    pass
                try:
                    proc.stdin.close()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    try:
                        proc.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        try:
                            proc.wait(timeout=1)
                        except subprocess.TimeoutExpired:
                            pass
        except Exception as e:
            logger.warning(f"Error stopping Chrome Screen AI worker: {e}")
        for f in (proc.stdin, proc.stdout, proc.stderr):
            try:
                if f:
                    f.close()
            except Exception:
                pass
        logger.debug("Chrome Screen AI worker stopped")

    async def recognize(self, image_data: bytes, language: str = "auto") -> List[TextRegion]:
        if not self._check_availability():
            raise OCRError(f"On-device OCR is unavailable: {self._init_error}")

        if self._persistent_mode:
            result = await asyncio.to_thread(self._recognize_via_worker, image_data)
            if result is not None:
                return result
            logger.warning("Chrome Screen AI worker unavailable, falling back to oneshot")

        return await asyncio.to_thread(self._recognize_oneshot, image_data)

    def _recognize_via_worker(self, image_data: bytes) -> Optional[List[TextRegion]]:
        if not self._is_worker_alive():
            if not self.start_worker():
                return None

        with tempfile.NamedTemporaryFile(prefix="chromescreenai_input_", suffix=".png", delete_on_close=False) as image_file:
            image_file.write(image_data)
            image_file.close()  # the worker opens it by name; it is deleted when the block ends
            temp_path = image_file.name

            request = {"type": "recognize", "image_path": temp_path}
            start = time.time()
            with self._worker_lock:
                if self._worker_proc is None or self._worker_proc.poll() is not None:
                    return None
                try:
                    self._worker_proc.stdin.write((json.dumps(request) + "\n").encode())
                    self._worker_proc.stdin.flush()
                    response_line = python_runtime.readline_with_timeout(self._worker_proc.stdout, OCR_TIMEOUT_SECONDS)
                except Exception as e:
                    logger.error(f"Chrome Screen AI worker I/O error: {e}")
                    self._kill_worker_unlocked()
                    return None

                if not response_line:
                    logger.error("Chrome Screen AI worker: no response (died or timed out)")
                    self._kill_worker_unlocked()
                    return None

                try:
                    response = json.loads(response_line.decode().strip())
                except json.JSONDecodeError as e:
                    # the real reply may still be in the pipe and would answer the next request: restart the worker
                    logger.error(f"Chrome Screen AI worker: bad JSON: {e}")
                    self._kill_worker_unlocked()
                    return None

            elapsed = time.time() - start
            if response.get("error"):
                raise OCRError(f"On-device OCR failed: {response['error']}")

            regions = []
            for r in response.get("regions", []):
                regions.append(TextRegion(
                    text=r["text"],
                    rect=r["rect"],
                    confidence=r["confidence"],
                    is_dialog=r.get("is_dialog", False),
                ))
            logger.debug(f"Chrome Screen AI (worker): {len(regions)} regions in {elapsed:.2f}s")
            return regions

    def _recognize_oneshot(self, image_data: bytes) -> List[TextRegion]:
        with tempfile.NamedTemporaryFile(prefix="chromescreenai_input_", suffix=".png", delete_on_close=False) as image_file:
            image_file.write(image_data)
            image_file.close()  # the subprocess opens it by name; it is deleted when the block ends
            temp_path = image_file.name
            start = time.time()

            env = os.environ.copy()
            env['PYTHONPATH'] = self._py_modules_dir
            env['PYTHONNOUSERSITE'] = '1'
            env['PYTHONDONTWRITEBYTECODE'] = '1'
            env['OMP_NUM_THREADS'] = '1'
            env['MKL_NUM_THREADS'] = '1'
            env['OPENBLAS_NUM_THREADS'] = '1'

            if not self._python_path:
                raise OCRError("On-device OCR is unavailable: no Python interpreter for it")

            cmd = [
                self._python_path, '-S', self._subprocess_script,
                temp_path, self._model_dir, str(self._min_confidence),
            ]
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, encoding='utf-8', errors='replace',
                    timeout=OCR_TIMEOUT_SECONDS, env=env, **python_runtime.popen_kwargs(),
                )
            except subprocess.TimeoutExpired:
                raise OCRError(f"On-device OCR timed out after {OCR_TIMEOUT_SECONDS} s") from None
            elapsed = time.time() - start
            if result.returncode != 0:
                logger.error(f"Chrome Screen AI subprocess error: {result.stderr}")
                raise OCRError(f"On-device OCR stopped with exit code {result.returncode} (details in the log)")

            try:
                output = json.loads(result.stdout)
            except json.JSONDecodeError as e:
                logger.error(f"Chrome Screen AI: unreadable output: {result.stdout[:500]}")
                raise OCRError("On-device OCR gave an unreadable answer (details in the log)") from e

            if output.get("debug"):
                for d in output["debug"]:
                    logger.debug(f"Chrome Screen AI subprocess: {d}")

            if output.get("error"):
                raise OCRError(f"On-device OCR failed: {output['error']}")

            regions = []
            for r in output.get("regions", []):
                regions.append(TextRegion(
                    text=r["text"],
                    rect=r["rect"],
                    confidence=r["confidence"],
                    is_dialog=r.get("is_dialog", False),
                ))
            logger.debug(f"Chrome Screen AI: {len(regions)} regions in {elapsed:.2f}s")
            return regions
