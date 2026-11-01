"""What the providers share: their interfaces, errors, HTTP requests and the background download of a model's files."""

import asyncio
import hashlib
import io
import json
import logging
import os
import shutil
import threading
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Optional

import aiohttp  # Decky Loader's own: its server runs on it, so the plugin doesn't ship one

logger = logging.getLogger(__name__)


class NetworkError(Exception):
    pass


class ApiKeyError(Exception):
    """The API key is invalid or missing."""


class RateLimitError(Exception):
    pass


def to_jpeg(image_data: bytes) -> bytes:
    """A screenshot as JPEG for the web OCR engines: about a tenth of the PNG (1.2 MB instead of 14.5 MB at 4K), so
    the upload is seconds shorter and stays under Google's request size limits. Same width and height, so the boxes
    the engines return need no scaling; quality 90 keeps small text sharp."""
    from PIL import Image
    out = io.BytesIO()
    Image.open(io.BytesIO(image_data)).convert("RGB").save(out, format="JPEG", quality=90)
    return out.getvalue()


class OCRError(Exception):
    """The OCR engine failed (which is not the same as finding no text); the message is shown to the user."""


class TranslationError(Exception):
    """The translation engine failed; the message is shown to the user."""


def classify_google_error(status_code: int, body: str) -> str:
    """Logging for a non-200 Google API response."""
    body = body or ""
    if 'API_KEY_INVALID' in body or 'API key not valid' in body:
        return "Invalid API key"
    if 'SERVICE_DISABLED' in body or 'has not been used' in body or 'it is disabled' in body:
        return "API not enabled in Cloud project"
    if 'BILLING_DISABLED' in body or 'billing' in body:
        return "Billing not enabled"
    if status_code == 401:
        return "Invalid API key"
    if status_code == 403:
        return "Access blocked (key restriction)"
    if status_code == 429:
        return "Rate limited"
    return f"API error ({status_code})"


def raise_for_google_error(resp: "Response") -> None:
    """A Google Cloud error the user has to act on (key, project, billing, quota) as ApiKeyError or RateLimitError;
    any other is only logged."""
    reason = classify_google_error(resp.status_code, resp.text)
    logger.error(f"Google API error {resp.status_code} ({reason}): {resp.text[:500]}")
    if reason == "Rate limited":
        raise RateLimitError(reason)
    if not reason.startswith("API error"):
        raise ApiKeyError(reason)


# -- HTTP for the web engines

@dataclass
class Response:
    status_code: int
    text: str
    headers: dict

    def json(self):
        return json.loads(self.text)


_session: Optional[aiohttp.ClientSession] = None


async def fetch(method: str, url: str, timeout: float = 10, **kwargs) -> Response:
    """One HTTP request through the engines' shared session (connections stay open between requests; a new TLS
    handshake per request doubled the time of short ones). Connection failures and timeouts raise NetworkError."""
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
    try:
        async with _session.request(method, url, timeout=aiohttp.ClientTimeout(total=timeout), **kwargs) as resp:
            headers = {name.lower(): value for name, value in resp.headers.items()}  # looked up lower-case
            return Response(resp.status, await resp.text(), headers)
    except asyncio.TimeoutError as e:
        raise NetworkError("Connection timed out") from e
    except aiohttp.ClientConnectionError as e:
        raise NetworkError("No internet connection") from e


def error_message(resp: Response) -> str:
    """The error text of a JSON API answer ({"error": {"message": ...}} or {"error": "..."}), else the start of the body."""
    try:
        body = resp.json()
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict):
            return str(err.get("message") or err)[:200]
        if err:
            return str(err)[:200]
    except ValueError:
        pass
    return (resp.text or "")[:200]


def raise_for_api_error(resp: Response, service: str) -> None:
    """A non-200 answer of an AI API (Gemini, OpenAI-compatible) as the plugin's errors: a bad key -> ApiKeyError,
    a rate limit -> RateLimitError, anything else -> NetworkError."""
    if resp.status_code == 200:
        return
    message = error_message(resp)
    if resp.status_code in (401, 403) or "API_KEY_INVALID" in message or "API key not valid" in message:
        raise ApiKeyError(f"{service}: invalid API key ({message})")
    if resp.status_code == 429:
        raise RateLimitError(f"{service}: rate limit ({message})")
    raise NetworkError(f"{service} error {resp.status_code}: {message}")


async def close_session() -> None:
    if _session is not None:
        await _session.close()


async def probe(method: str, url: str, **kwargs) -> tuple:
    """A reachability probe: (response, "") or (None, why it failed)."""
    try:
        return await fetch(method, url, timeout=4, **kwargs), ""
    except NetworkError:
        return None, "Network unreachable"
    except Exception as e:  # noqa: BLE001
        return None, f"Probe failed: {type(e).__name__}"


@dataclass
class TextRegion:
    text: str
    rect: Dict[str, int]  # left, top, right, bottom
    confidence: Optional[float] = None  # None: the engine reports none
    translated_text: Optional[str] = None  # from an engine that translates while it reads (Gemini Vision)

    def to_dict(self) -> Dict:
        """The region as the frontend reads it."""
        d = {
            "text": self.text,
            "rect": self.rect,
        }
        if self.translated_text is not None:
            d["translatedText"] = self.translated_text
        return d


class OCRProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Shown to the user, e.g. in error messages."""

    @abstractmethod
    async def recognize(self, image_data: bytes, language: str = "auto") -> List[TextRegion]:
        """The text regions of a PNG or JPEG image; language is a code or "auto"."""

    @abstractmethod
    def is_available(self) -> bool:
        """Configured and installed: a key set, a model downloaded."""


class TranslationProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Shown to the user, e.g. in error messages."""

    @abstractmethod
    async def translate_batch(self, texts: List[str], source_lang: str, target_lang: str) -> List[str]:
        """The translations, in the order of texts."""

    @abstractmethod
    def is_available(self, source_lang: str, target_lang: str) -> bool:
        """Whether the provider can handle this language pair."""


def chunk_indices(texts: List[str], max_chars: int, max_items: Optional[int] = None,
                  sep_chars: int = 0) -> List[List[int]]:
    """The indices of the non-blank texts, in order, grouped into requests: each group's total length (every text
    plus sep_chars, e.g. 1 for the newline joining them) stays within max_chars and, if given, max_items texts.
    A text longer than max_chars gets a group of its own."""
    chunks: List[List[int]] = []
    cur: List[int] = []
    size = 0
    for i, t in enumerate(texts):
        if not t or not t.strip():
            continue
        n = len(t) + sep_chars
        if cur and (size + n > max_chars or (max_items is not None and len(cur) >= max_items)):
            chunks.append(cur)
            cur, size = [], 0
        cur.append(i)
        size += n
    if cur:
        chunks.append(cur)
    return chunks


# -- the background download of a model's files

_DOWNLOAD_CHUNK_BYTES = 256 * 1024


class DownloadError(Exception):
    """Why a model download stopped; the message is shown in the settings."""


class Downloader:
    """A model's files, downloaded in a background thread (progress, cancel, the reason it failed) into
    <models_dir>/<name>: staged next to it and moved into place only when complete. urllib in that thread (the
    plugin's aiohttp lives on the event loop). A subclass sets name, approx_size_mb and required_files and fills
    the staging folder in _install()."""

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
                while chunk := resp.read(_DOWNLOAD_CHUNK_BYTES):
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
