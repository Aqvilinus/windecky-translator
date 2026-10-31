# providers/model_download.py
# A model the user downloads from the settings (the NLLB translation model, the Chrome Screen AI engine): fetched in a
# background thread with progress, cancel and the reason it failed, staged next to its folder and moved into place
# only when complete. The downloads use urllib in that thread (the plugin's aiohttp lives on the event loop).

import hashlib
import logging
import os
import shutil
import threading
import urllib.error
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

CHUNK = 256 * 1024


class DownloadError(Exception):
    """Why a model download stopped; the message is shown in the settings."""


class ModelDownload:
    """A model installed in <models_dir>/<name>. A subclass sets name, approx_size_mb and required_files and fills the
    staging folder in _install()."""

    name = ""                 # the model's folder in models_dir
    approx_size_mb = 0        # shown before the model is installed
    required_files = ()       # paths inside the folder that make it complete

    def __init__(self, models_dir: str):
        self.target_dir = os.path.join(models_dir, self.name)
        self._staging_dir = self.target_dir + ".downloading"
        self._lock = threading.Lock()
        self._downloading = False
        self._progress = 0.0
        self._error: Optional[str] = None
        self._cancel = False
        os.makedirs(models_dir, exist_ok=True)
        shutil.rmtree(self._staging_dir, ignore_errors=True)  # an interrupted download

    # ---- state, for the settings
    def is_installed(self) -> bool:
        return all(os.path.exists(os.path.join(self.target_dir, f)) for f in self.required_files)

    def status(self) -> dict:
        size = sum(os.path.getsize(os.path.join(root, f)) for root, _, files in os.walk(self.target_dir)
                   for f in files) if self.is_installed() else 0
        with self._lock:
            return {"downloaded": self.is_installed(), "size": size, "approx_size_mb": self.approx_size_mb,
                    "downloading": self._downloading, "progress": self._progress, "error": self._error}

    # ---- actions
    def start(self) -> bool:
        """Start the download in a thread; False if one is running."""
        with self._lock:
            if self._downloading:
                return False
            self._downloading, self._progress, self._error, self._cancel = True, 0.0, None, False
        threading.Thread(target=self._run, name=f"download-{self.name}", daemon=True).start()
        return True

    def cancel(self):
        with self._lock:
            self._cancel = True

    def clear_error(self):
        with self._lock:
            self._error = None

    def delete(self) -> bool:
        try:
            shutil.rmtree(self.target_dir)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.error(f"Could not delete {self.name}: {e}")
            return False
        logger.info(f"Deleted {self.name}")
        return True

    # ---- for subclasses
    def _install(self, staging_dir: str) -> None:
        """Download the model into staging_dir (raise DownloadError to stop)."""
        raise NotImplementedError

    def _set_progress(self, fraction: float) -> None:
        with self._lock:
            self._progress = fraction

    def _check_cancel(self) -> None:
        if self._cancel:
            raise DownloadError("Download cancelled")

    def _fetch(self, url: str, dest: str, hash_name: str = "sha256", max_mb: Optional[int] = None,
               progress=None, timeout: int = 60) -> str:
        """url -> dest, streamed; returns the file's hex digest. progress(fraction) follows the download when the
        server gives its size. max_mb guards the disk against an unexpected answer (the hash is only known at the
        end)."""
        hasher = hashlib.new(hash_name)
        limit = (max_mb or self.approx_size_mb * 2) * 1024 * 1024
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp, open(dest, "wb") as f:
                total = int(resp.headers.get("Content-Length") or 0)
                if total > limit:
                    raise DownloadError(f"The server offers {total // 2**20} MB, more than expected: not downloaded")
                done = 0
                while chunk := resp.read(CHUNK):
                    self._check_cancel()
                    done += len(chunk)
                    if done > limit:
                        raise DownloadError("The download is bigger than expected: stopped")
                    f.write(chunk)
                    hasher.update(chunk)
                    if progress and total:
                        progress(done / total)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                raise DownloadError("Too many requests. Try again later.") from e
            raise DownloadError(f"HTTP {e.code} downloading {os.path.basename(dest)}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise DownloadError("Cannot reach the download server. Check the internet connection.") from e
        return hasher.hexdigest()

    # ---- the download thread
    def _run(self):
        try:
            shutil.rmtree(self._staging_dir, ignore_errors=True)
            os.makedirs(self._staging_dir)
            self._install(self._staging_dir)
            self._check_cancel()
            missing = [f for f in self.required_files if not os.path.exists(os.path.join(self._staging_dir, f))]
            if missing:
                raise DownloadError(f"Missing after download: {', '.join(missing)}")
            shutil.rmtree(self.target_dir, ignore_errors=True)
            os.rename(self._staging_dir, self.target_dir)
            with self._lock:
                self._progress, self._downloading = 1.0, False
            logger.info(f"{self.name} downloaded")
        except Exception as e:  # noqa: BLE001 - any failure ends the download with its reason shown
            shutil.rmtree(self._staging_dir, ignore_errors=True)
            if not isinstance(e, DownloadError):
                logger.exception(f"{self.name} download failed")
            with self._lock:
                self._error, self._downloading = str(e), False
            logger.error(f"{self.name} download failed: {e}")
