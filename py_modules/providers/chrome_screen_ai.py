"""Local OCR via Chrome Screen AI. The DLL and TFLite models are fetched on demand from Google's CIPD server, not
bundled in the plugin."""

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from typing import List, Optional

from .base import DownloadError, Downloader, OCRError, OCRProvider, TextRegion
from .worker import PLUGIN_DIR, Worker, find_python, missing_message, popen_kwargs, worker_pythonpath

logger = logging.getLogger(__name__)

DEFAULT_MIN_CONFIDENCE = 0.5
SCREENAI_LIBRARY = "chrome_screen_ai.dll"
OCR_TIMEOUT_SECONDS = 30  # a screen takes about a second; a hung engine must not hold a paused game long
WORKER_READY_TIMEOUT_SECONDS = 60

_THREAD_LIMIT_VARS = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


class ChromeScreenAIProvider(OCRProvider):
    """OCR provider backed by chrome_screen_ai.dll. Oneshot subprocess by
    default; persistent worker is opt-in for lower per-call latency."""

    # The engine detects the script itself (77+ of them); these are the plugin's languages plus 'auto'.
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
        self._plugin_dir = plugin_dir or os.environ.get("DECKY_PLUGIN_DIR", PLUGIN_DIR)
        # model_dir holds the DLL and TFLite files (ChromeScreenAIDownloader below).
        self._model_dir = model_dir
        self._min_confidence = max(0.0, min(1.0, min_confidence))
        self._init_error: Optional[str] = None
        self._python_path: Optional[str] = None

        self._persistent_mode = False
        self._start_lock = threading.Lock()

        # Prefer the extracted bin/py_modules copy (Decky Store install),
        # fall back to root py_modules in dev.
        bin_script = os.path.join(
            self._plugin_dir, "bin", "py_modules", "providers",
            "chrome_screen_ai_worker.py",
        )
        root_script = os.path.join(
            self._plugin_dir, "py_modules", "providers",
            "chrome_screen_ai_worker.py",
        )
        self._subprocess_script = bin_script if os.path.exists(bin_script) else root_script

        self._py_modules_dir = worker_pythonpath(self._plugin_dir)
        # the engine picks its own thread count: don't pass the plugin's limits on
        self._worker = Worker("Chrome Screen AI", self._subprocess_script, ["--worker"],
                                      env={k: None for k in _THREAD_LIMIT_VARS})

        logger.debug(
            f"ChromeScreenAIProvider initialized "
            f"(model_dir={self._model_dir}, min_confidence={min_confidence})"
        )

    @property
    def name(self) -> str:
        return "Chrome Screen AI (Local)"

    def _check_availability(self) -> bool:
        self._init_error = None

        if not os.path.exists(self._subprocess_script):
            self._init_error = (
                f"Chrome Screen AI subprocess script missing: {self._subprocess_script}"
            )
            logger.warning(self._init_error)
            return False

        so_path = os.path.join(self._model_dir or "", SCREENAI_LIBRARY)
        if not self._model_dir or not os.path.exists(so_path):
            self._init_error = "Chrome Screen AI engine not downloaded"
            return False

        self._python_path = find_python(self._plugin_dir)
        if not self._python_path:
            self._init_error = missing_message()
            logger.warning(self._init_error)
            return False

        return True

    def is_available(self, language: str = "auto") -> bool:
        if not self._check_availability():
            return False
        return language in self.SUPPORTED_LANGUAGES

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

    def start_worker(self) -> bool:
        """Start the persistent worker and load the engine into it."""
        with self._start_lock:
            if self._worker.alive:
                return True
            if not self._persistent_mode or not self._check_availability():
                return False
            if not self._worker.start(self._python_path, self._py_modules_dir):
                return False
            start = time.time()
            ready = self._worker.request({"type": "init", "model_dir": self._model_dir,
                                          "min_confidence": self._min_confidence}, WORKER_READY_TIMEOUT_SECONDS)
            if not ready or ready.get("error"):
                logger.error(f"Chrome Screen AI worker init failed: {(ready or {}).get('error') or 'no answer'}")
                self._worker.stop()
                return False
            logger.info(f"Chrome Screen AI worker ready ({time.time() - start:.2f}s)")
            return True

    def stop_worker(self) -> None:
        self._worker.stop({"type": "shutdown"})

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
        """The persistent worker's answer; None if it isn't available (the caller falls back to a one-shot run)."""
        if not self._worker.alive and not self.start_worker():
            return None
        with tempfile.NamedTemporaryFile(prefix="chromescreenai_input_", suffix=".png", delete_on_close=False) as image_file:
            image_file.write(image_data)
            image_file.close()  # the worker opens it by name; it is deleted when the block ends
            start = time.time()
            response = self._worker.request({"type": "recognize", "image_path": image_file.name}, OCR_TIMEOUT_SECONDS)
        if response is None:
            return None
        if response.get("error"):
            raise OCRError(f"On-device OCR failed: {response['error']}")
        regions = [TextRegion(text=r["text"], rect=r["rect"], confidence=r["confidence"])
                   for r in response.get("regions", [])]
        logger.debug(f"Chrome Screen AI (worker): {len(regions)} regions in {time.time() - start:.2f}s")
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
                    timeout=OCR_TIMEOUT_SECONDS, env=env, **popen_kwargs(),
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
                ))
            logger.debug(f"Chrome Screen AI: {len(regions)} regions in {elapsed:.2f}s")
            return regions


# ---- the engine's download: chrome_screen_ai.dll + TFLite models from Google's CIPD package server

# Chrome's Screen AI component for Windows x64 (an ~80 MB zip)
CIPD_PACKAGE = "chromium/third_party/screen-ai/windows-amd64"
# Accepts a tag/ref or a 64-char SHA256 digest; "latest" tracks Chrome Stable.
CIPD_VERSION = "latest"
CIPD_HOST = "https://chrome-infra-packages.appspot.com"
PRPC_RESOLVE = f"{CIPD_HOST}/prpc/cipd.Repository/ResolveVersion"
PRPC_GET_URL = f"{CIPD_HOST}/prpc/cipd.Repository/GetInstanceURL"
# pRPC responses are prefixed with )]}' to defeat JSON hijacking.
PRPC_PREFIX = b")]}'"

APPROX_SIZE_MB = 80
# CIPD package nests everything under resources/ at the zip root.
RESOURCES_SUBDIR = "resources"


class ChromeScreenAIDownloader(Downloader):
    name = "screen_ai"
    approx_size_mb = APPROX_SIZE_MB
    required_files = (os.path.join(RESOURCES_SUBDIR, SCREENAI_LIBRARY),)

    @property
    def resources_dir(self) -> str:
        """The OCR worker's model_dir: the DLL loads its TFLite models from paths relative to its own folder."""
        return os.path.join(self.target_dir, RESOURCES_SUBDIR)

    def _install(self, staging_dir: str) -> None:
        signed_url, hash_algo, hex_digest = self._resolve_signed_url()
        self._check_cancel()
        package = os.path.join(staging_dir, "package.zip")
        # the package holds a native library the OCR worker loads: check it is exactly the instance CIPD named
        try:
            digest = self._fetch(signed_url, package, hash_name=hash_algo.lower(),
                                 progress=lambda f: self._set_progress(f * 0.95))  # the rest is the unzip
        except ValueError as e:  # hashlib doesn't know the algorithm
            raise DownloadError(f"Unsupported package hash: {hash_algo}") from e
        if digest != str(hex_digest).lower():
            raise DownloadError("Downloaded package is damaged or not the expected one (hash mismatch)")
        logger.info(f"Chrome Screen AI package verified ({hash_algo} {hex_digest[:12]}...)")
        try:
            with zipfile.ZipFile(package) as zf:
                zf.extractall(staging_dir)
        except zipfile.BadZipFile as e:
            raise DownloadError("Downloaded package is not a valid zip") from e
        os.remove(package)
        shutil.rmtree(os.path.join(staging_dir, ".cipdpkg"), ignore_errors=True)  # CIPD's manifest

    def _prpc_post(self, url: str, payload: dict) -> dict:
        request = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=30) as resp:
                body = resp.read()
        except urllib.error.HTTPError as e:
            raise DownloadError(f"Package server: HTTP {e.code}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise DownloadError("Cannot reach the download server. Check the internet connection.") from e
        if body.startswith(PRPC_PREFIX):
            body = body[len(PRPC_PREFIX):]
        return json.loads(body.decode("utf-8"))

    def _resolve_signed_url(self):
        """(download URL, hash algorithm, hex digest): CIPD names an instance by the hash of its package file."""
        # ResolveVersion only takes tags/refs; a 64-char hex digest is already the instance
        if re.fullmatch(r"[0-9a-f]{64}", CIPD_VERSION):
            hash_algo, hex_digest = "SHA256", CIPD_VERSION
        else:
            resolved = self._prpc_post(PRPC_RESOLVE, {"package": CIPD_PACKAGE, "version": CIPD_VERSION})
            instance = resolved.get("instance") or {}
            hash_algo, hex_digest = instance.get("hashAlgo"), instance.get("hexDigest")
            if not hash_algo or not hex_digest:
                raise DownloadError(f"The package server named no package: {resolved}")
        url_resp = self._prpc_post(PRPC_GET_URL, {
            "package": CIPD_PACKAGE,
            "instance": {"hashAlgo": hash_algo, "hexDigest": hex_digest},
        })
        signed = url_resp.get("signedUrl")
        if not signed:
            raise DownloadError(f"The package server gave no download address: {url_resp}")
        return signed, hash_algo, hex_digest
