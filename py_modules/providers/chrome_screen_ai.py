"""Local OCR via Chrome Screen AI. The DLL and TFLite models are fetched on demand from Google's CIPD server, not
bundled in the plugin."""

import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from typing import List, Optional

from .base import DownloadError, Downloader, OCRError, OCRProvider, TextRegion
from .worker import Worker, find_python, missing_message, worker_pythonpath

logger = logging.getLogger(__name__)

WORKER_SCRIPT = os.path.join(os.path.dirname(__file__), "chrome_screen_ai_worker.py")
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
    """chrome_screen_ai.dll in a worker process: up between requests with Faster Recognition, else started and
    stopped for each one."""

    def __init__(self, model_dir: str = ""):
        # model_dir holds the DLL and TFLite files (ChromeScreenAIDownloader below).
        self._model_dir = model_dir
        self._init_error: Optional[str] = None
        self._python_path: Optional[str] = None

        self._persistent_mode = False
        self._lock = threading.Lock()

        self._py_modules_dir = worker_pythonpath()
        # the engine picks its own thread count: don't pass the plugin's limits on
        self._worker = Worker("Chrome Screen AI", WORKER_SCRIPT,
                              env={k: None for k in _THREAD_LIMIT_VARS})

    @property
    def name(self) -> str:
        return "Chrome Screen AI (Local)"

    def _check_availability(self) -> bool:
        self._init_error = None

        so_path = os.path.join(self._model_dir or "", SCREENAI_LIBRARY)
        if not self._model_dir or not os.path.exists(so_path):
            self._init_error = "Chrome Screen AI engine not downloaded"
            return False

        self._python_path = find_python()
        if not self._python_path:
            self._init_error = missing_message()
            logger.warning(self._init_error)
            return False

        return True

    def is_available(self) -> bool:
        return self._check_availability()

    def set_persistent_mode(self, enabled: bool) -> None:
        """Faster Recognition: the worker stays up between requests (started now, so the first one is fast too)."""
        enabled = bool(enabled)
        if enabled == self._persistent_mode:
            return
        self._persistent_mode = enabled
        logger.info(f"Chrome Screen AI persistent mode: {enabled}")
        if enabled:
            threading.Thread(target=self._warm_up, daemon=True).start()
        else:
            self.stop_worker()

    def _warm_up(self) -> None:
        with self._lock:
            if self._persistent_mode and self._check_availability():
                try:
                    self._start_worker()
                except OCRError as e:
                    logger.error(e)

    def _start_worker(self) -> None:
        if self._worker.alive:
            return
        if not self._worker.start(self._python_path, self._py_modules_dir):
            raise OCRError("On-device OCR could not start (details in the plugin log)")
        start = time.time()
        ready = self._worker.request({"type": "init", "model_dir": self._model_dir}, WORKER_READY_TIMEOUT_SECONDS)
        if not ready or ready.get("error"):
            self._worker.stop()
            logger.error(f"Chrome Screen AI init failed: {(ready or {}).get('error') or 'no answer'}")
            raise OCRError("On-device OCR could not load its engine (details in the plugin log)")
        logger.info(f"Chrome Screen AI worker ready ({time.time() - start:.2f}s)")

    def stop_worker(self) -> None:
        self._worker.stop({"type": "shutdown"})

    async def recognize(self, image_data: bytes, language: str = "auto") -> List[TextRegion]:
        if not self._check_availability():
            raise OCRError(f"On-device OCR is unavailable: {self._init_error}")
        return await asyncio.to_thread(self._recognize, image_data)

    def _recognize(self, image_data: bytes) -> List[TextRegion]:
        with self._lock:
            try:
                self._start_worker()
                with tempfile.NamedTemporaryFile(prefix="chromescreenai_input_", suffix=".png",
                                                 delete_on_close=False) as image_file:
                    image_file.write(image_data)
                    image_file.close()  # the worker opens it by name; it is deleted when the block ends
                    start = time.time()
                    response = self._worker.request({"type": "recognize", "image_path": image_file.name},
                                                    OCR_TIMEOUT_SECONDS)
            finally:
                if not self._persistent_mode:
                    self.stop_worker()
        if response is None:
            raise OCRError(f"On-device OCR didn't answer in {OCR_TIMEOUT_SECONDS} s (details in the plugin log)")
        if response.get("error"):
            raise OCRError(f"On-device OCR failed: {response['error']}")
        regions = [TextRegion(text=r["text"], rect=r["rect"], confidence=r.get("confidence"))
                   for r in response.get("regions", [])]
        logger.debug(f"Chrome Screen AI: {len(regions)} regions in {time.time() - start:.2f}s")
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
