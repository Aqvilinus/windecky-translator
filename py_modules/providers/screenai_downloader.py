# Fetches chrome_screen_ai.dll + TFLite models from Google's CIPD server.
# Threading and progress shape mirror NLLBDownloader so the UI treats both alike.

import hashlib
import json
import logging
import os
import re
import shutil
import threading
import urllib.error
import urllib.request
import zipfile
from typing import Dict, Optional

from .python_runtime import SCREENAI_LIBRARY

logger = logging.getLogger(__name__)

# Chrome's Screen AI component for Windows x64 (chrome_screen_ai.dll + TFLite models, an ~80 MB zip)
CIPD_PACKAGE = "chromium/third_party/screen-ai/windows-amd64"
LIBRARY = SCREENAI_LIBRARY
# Accepts a tag/ref or a 64-char SHA256 digest; "latest" tracks Chrome Stable.
CIPD_VERSION = "latest"
CIPD_HOST = "https://chrome-infra-packages.appspot.com"
PRPC_RESOLVE = f"{CIPD_HOST}/prpc/cipd.Repository/ResolveVersion"
PRPC_GET_URL = f"{CIPD_HOST}/prpc/cipd.Repository/GetInstanceURL"

# pRPC responses are prefixed with )]}' to defeat JSON hijacking.
PRPC_PREFIX = b")]}'"

SCREENAI_DIR_NAME = "screen_ai"

# Shown in the UI before the real Content-Length is known.
APPROX_SIZE_MB = 80

# CIPD package nests everything under resources/ at the zip root.
RESOURCES_SUBDIR = "resources"
REQUIRED_FILES = (os.path.join(RESOURCES_SUBDIR, LIBRARY),)


class ScreenAIDownloader:
    """Handles fetching and managing the Chrome Screen AI library package."""

    def __init__(self, base_dir: str):
        # base_dir is the shared models/ folder; we extract into base_dir/screen_ai/.
        self._base_dir = base_dir
        self._target_dir = os.path.join(base_dir, SCREENAI_DIR_NAME)

        self._downloading = False
        self._download_progress = 0.0  # 0.0 - 1.0
        self._download_error: Optional[str] = None
        self._download_cancel = False
        self._download_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        os.makedirs(base_dir, exist_ok=True)
        self._cleanup_partial()

    def _cleanup_partial(self):
        try:
            for item in os.listdir(self._base_dir):
                if item.endswith(".downloading") or item.endswith(".tmpzip"):
                    p = os.path.join(self._base_dir, item)
                    if os.path.isdir(p):
                        shutil.rmtree(p, ignore_errors=True)
                    elif os.path.isfile(p):
                        try:
                            os.remove(p)
                        except OSError:
                            pass
        except Exception as e:
            logger.error(f"ScreenAIDownloader: cleanup error: {e}")

    def get_target_dir(self) -> str:
        return self._target_dir

    def get_resources_dir(self) -> str:
        # The .so loads its TFLite models via paths relative to its own location,
        # so the provider must use this dir as model_dir.
        return os.path.join(self._target_dir, RESOURCES_SUBDIR)

    def is_installed(self) -> bool:
        if not os.path.isdir(self._target_dir):
            return False
        return all(
            os.path.exists(os.path.join(self._target_dir, f))
            for f in REQUIRED_FILES
        )

    def get_install_size(self) -> int:
        if not os.path.isdir(self._target_dir):
            return 0
        total = 0
        for root, _, files in os.walk(self._target_dir):
            for f in files:
                fp = os.path.join(root, f)
                if os.path.isfile(fp):
                    try:
                        total += os.path.getsize(fp)
                    except OSError:
                        pass
        return total

    def get_approx_size_mb(self) -> int:
        return APPROX_SIZE_MB

    def get_status(self) -> Dict:
        with self._lock:
            return {
                "downloaded": self.is_installed(),
                "size": self.get_install_size(),
                "approx_size_mb": APPROX_SIZE_MB,
                "downloading": self._downloading,
                "progress": self._download_progress,
                "error": self._download_error,
            }

    def start_download(self) -> bool:
        with self._lock:
            if self._downloading:
                return False
            self._downloading = True
            self._download_progress = 0.0
            self._download_error = None
            self._download_cancel = False

        self._download_thread = threading.Thread(
            target=self._download, daemon=True
        )
        self._download_thread.start()
        return True

    def cancel_download(self):
        with self._lock:
            self._download_cancel = True

    def clear_error(self):
        with self._lock:
            self._download_error = None

    def delete(self) -> bool:
        if os.path.isdir(self._target_dir):
            try:
                shutil.rmtree(self._target_dir)
                logger.info("ScreenAIDownloader: deleted Screen AI files")
                return True
            except Exception as e:
                logger.error(f"ScreenAIDownloader: delete failed: {e}")
                return False
        return True

    def _prpc_post(self, url: str, payload: dict) -> dict:
        request = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=30) as resp:
                body = resp.read()
        except urllib.error.HTTPError as e:
            raise Exception(f"pRPC HTTP {e.code}: {e.read()[:200]!r}")
        except (urllib.error.URLError, TimeoutError):
            raise Exception("Cannot reach the remote resource. Check internet connection.")
        if body.startswith(PRPC_PREFIX):
            body = body[len(PRPC_PREFIX):]
        return json.loads(body.decode("utf-8"))

    def _resolve_signed_url(self):
        """(download URL, hash algorithm, hex digest): CIPD names an instance by the hash of its package file."""
        # ResolveVersion only takes tags/refs; if CIPD_VERSION is already
        # a 64-char hex digest, skip the resolve step.
        if re.fullmatch(r"[0-9a-f]{64}", CIPD_VERSION):
            hash_algo = "SHA256"
            hex_digest = CIPD_VERSION
        else:
            resolved = self._prpc_post(PRPC_RESOLVE, {
                "package": CIPD_PACKAGE,
                "version": CIPD_VERSION,
            })
            instance = resolved.get("instance") or {}
            hash_algo = instance.get("hashAlgo")
            hex_digest = instance.get("hexDigest")
            if not hash_algo or not hex_digest:
                raise Exception(f"CIPD resolve returned no instance: {resolved}")

        url_resp = self._prpc_post(PRPC_GET_URL, {
            "package": CIPD_PACKAGE,
            "instance": {"hashAlgo": hash_algo, "hexDigest": hex_digest},
        })
        signed = url_resp.get("signedUrl")
        if not signed:
            raise Exception(f"CIPD GetInstanceURL returned no URL: {url_resp}")
        return signed, hash_algo, hex_digest

    def _download(self):
        zip_path = os.path.join(self._base_dir, f"{SCREENAI_DIR_NAME}.tmpzip")
        staging_dir = os.path.join(
            self._base_dir, f"{SCREENAI_DIR_NAME}.downloading"
        )

        try:
            signed_url, hash_algo, hex_digest = self._resolve_signed_url()
            # the package holds a native library the OCR worker loads: check it is exactly the instance CIPD named
            try:
                hasher = hashlib.new(hash_algo.lower())
            except (ValueError, AttributeError):
                raise Exception(f"Unsupported package hash: {hash_algo}")

            if self._download_cancel:
                raise Exception("Download cancelled")

            try:
                with urllib.request.urlopen(signed_url, timeout=60) as resp, open(zip_path, "wb") as f:
                    total = int(resp.headers.get("Content-Length") or 0)
                    downloaded = 0
                    while chunk := resp.read(1024 * 256):
                        if self._download_cancel:
                            raise Exception("Download cancelled")
                        f.write(chunk)
                        hasher.update(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            with self._lock:
                                # Cap at 95% so the bar isn't pinned during unzip.
                                self._download_progress = min(0.95, downloaded / total * 0.95)
            except urllib.error.HTTPError as e:
                raise Exception(f"HTTP {e.code} fetching package")
            except (urllib.error.URLError, TimeoutError):
                raise Exception("Cannot reach the remote resource. Check internet connection.")

            if self._download_cancel:
                raise Exception("Download cancelled")

            if hasher.hexdigest().lower() != str(hex_digest).lower():
                raise Exception("Downloaded package is damaged or not the expected one (hash mismatch)")
            logger.info(f"Chrome Screen AI package verified ({hash_algo} {hex_digest[:12]}...)")

            if os.path.exists(staging_dir):
                shutil.rmtree(staging_dir, ignore_errors=True)
            os.makedirs(staging_dir, exist_ok=True)

            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(staging_dir)
            except zipfile.BadZipFile:
                raise Exception("Downloaded package is not a valid zip")

            # Drop the .cipdpkg manifest dir; not needed at runtime.
            cipd_meta = os.path.join(staging_dir, ".cipdpkg")
            if os.path.isdir(cipd_meta):
                shutil.rmtree(cipd_meta, ignore_errors=True)

            for req in REQUIRED_FILES:
                if not os.path.exists(os.path.join(staging_dir, req)):
                    raise Exception(f"Missing required file after extract: {req}")

            if os.path.exists(self._target_dir):
                shutil.rmtree(self._target_dir)
            os.rename(staging_dir, self._target_dir)

            try:
                os.remove(zip_path)
            except OSError:
                pass

            with self._lock:
                self._download_progress = 1.0
                self._downloading = False

            logger.info("Chrome Screen AI files downloaded successfully")

        except Exception as e:
            for p in (zip_path, staging_dir):
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                elif os.path.isfile(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

            with self._lock:
                self._download_error = str(e)
                self._downloading = False

            logger.error(f"Chrome Screen AI download failed: {e}")
