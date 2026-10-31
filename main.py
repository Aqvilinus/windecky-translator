# main.py
import asyncio
import functools
import os
import sys
import tempfile
import traceback
import time
from datetime import datetime
from pathlib import Path
import logging
import re
import json
import base64
import sqlite3
import tarfile

# IMPORTANT: Set up plugin directory FIRST
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

# Auto-extract dependencies archive if needed (for Decky Store installs)
# This must happen BEFORE importing third-party libraries
BIN_DIR = os.path.join(PLUGIN_DIR, "bin")
DEPENDENCIES_ARCHIVE = os.path.join(BIN_DIR, "plugin-dependencies.tar.gz")
EXTRACTION_MARKER = os.path.join(BIN_DIR, ".dependencies-extracted")
# The archive (scripts/build_windows.py) holds py_modules (cp314 wheels) and python314 (the workers' interpreter)
BIN_PY_MODULES_DIR = os.path.join(BIN_DIR, "py_modules")
BIN_PYTHON_DIR = os.path.join(BIN_DIR, "python314")

def _should_extract_dependencies():
    """Check if dependencies archive needs to be extracted."""
    if not os.path.exists(DEPENDENCIES_ARCHIVE):
        return False  # No dependencies archive to extract

    # Check if extraction marker exists
    if not os.path.exists(EXTRACTION_MARKER):
        return True  # Never extracted successfully

    # Check if dependencies were updated (archive is newer than marker)
    archive_mtime = os.path.getmtime(DEPENDENCIES_ARCHIVE)
    marker_mtime = os.path.getmtime(EXTRACTION_MARKER)
    if archive_mtime > marker_mtime:
        return True  # Dependencies were updated, need to re-extract

    # Check if all expected directories exist (partial extraction detection)
    if not all(os.path.exists(d) for d in [BIN_PY_MODULES_DIR, BIN_PYTHON_DIR]):
        return True  # Some directories missing, need to re-extract

    return False  # Already extracted and up-to-date

if _should_extract_dependencies():
    try:
        print(f"[WinDecky Translator] Extracting dependencies from {DEPENDENCIES_ARCHIVE}...")
        with tarfile.open(DEPENDENCIES_ARCHIVE, "r:gz") as tar:
            tar.extractall(path=BIN_DIR, filter="data")  # no links or paths out of BIN_DIR (3.14's default too)
        # Create marker file to indicate successful extraction
        with open(EXTRACTION_MARKER, "w", encoding="utf-8") as f:
            f.write(f"Extracted at {datetime.now().isoformat()}\n")
        print("[WinDecky Translator] Dependencies extracted successfully")
    except Exception as e:
        print(f"[WinDecky Translator] Failed to extract dependencies: {e}")
        # Remove marker if it exists, so we retry next time
        if os.path.exists(EXTRACTION_MARKER):
            os.remove(EXTRACTION_MARKER)

# Add py_modules to path
# Root py_modules always needed (contains providers/ source code)
# bin/py_modules needed for store installs (pip packages from remote_binary)
ROOT_PY_MODULES_DIR = os.path.join(PLUGIN_DIR, "py_modules")

if ROOT_PY_MODULES_DIR not in sys.path:
    sys.path.insert(0, ROOT_PY_MODULES_DIR)

if os.path.exists(BIN_PY_MODULES_DIR) and BIN_PY_MODULES_DIR not in sys.path:
    sys.path.insert(0, BIN_PY_MODULES_DIR)

# Decky's frozen Python has python314.dll but not python3.dll, which stable-ABI extensions (psutil) load: the bundled
# runtime has it
if os.path.isdir(os.path.join(BIN_PYTHON_DIR, "python")):
    os.add_dll_directory(os.path.join(BIN_PYTHON_DIR, "python"))

# Now import third-party libraries (after sys.path is configured)
import decky  # Decky Loader's plugin API (typings/decky.pyi)

# Import provider system
from providers import ProviderManager, NetworkError, ApiKeyError, RateLimitError, OCRError, TranslationError
from providers.base import close_session
from providers.translation_cache import TranslationCache, PROVIDER_TIERS, normalize

_processing_lock = False

SENSITIVE_SETTING_KEYS = {
    "groq_api_key",
    "llm_custom_api_key",
    "google_api_key",
    "gemini_api_key",
}

# Every setting and its default: what get_all_settings answers, the only keys set_setting stores
SETTING_DEFAULTS = {
    "enabled": True,
    "target_language": "en",
    "input_language": "auto",
    "ocr_provider": "chromescreenai",       # "chromescreenai", "windows_ocr", "ocrspace", "googlecloud", "gemini_vision"
    "translation_provider": "freegoogle",   # "freegoogle", "googlecloud", "ct2" (offline NLLB) or "llm" (AI)
    "google_api_key": "",                   # one Google Cloud key for Vision and Translation
    "gemini_api_key": "",                   # Gemini Vision, and AI translation through Gemini
    "gemini_model": "gemini-3.5-flash",     # Gemini Vision's model
    "chromescreenai_persistent_mode": False,  # "Faster Recognition": the Screen AI worker stays up between requests
    "ct2_persistent_mode": False,           # the same for the offline NLLB worker
    "pause_game_on_overlay": False,
    "translation_cache_enabled": True,
    "debug_mode": False,
    # used by the frontend only
    "font_scale": 1.0,
    "confidence_threshold": 0.6,
    "custom_recognition_settings": False,
    # AI translation (translation_provider "llm", providers/llm_translate.py)
    "llm_backend": "gemini",                # "gemini", "groq" or "custom" (any OpenAI-compatible server)
    "llm_gemini_model": "gemini-flash-lite-latest",
    "llm_groq_model": "openai/gpt-oss-120b",
    "llm_custom_model": "",
    "llm_custom_url": "",                   # e.g. https://openrouter.ai/api/v1 or http://127.0.0.1:8081/v1
    "groq_api_key": "",
    "llm_custom_api_key": "",
}
# Settings the provider manager gets (_configure_providers) and those that decide which workers run (_sync_workers)
PROVIDER_SETTINGS = {"ocr_provider", "translation_provider", "google_api_key", "gemini_api_key", "gemini_model",
                     "llm_backend", "llm_gemini_model", "llm_groq_model", "llm_custom_model", "llm_custom_url",
                     "groq_api_key", "llm_custom_api_key"}
WORKER_SETTINGS = {"enabled", "ocr_provider", "translation_provider", "chromescreenai_persistent_mode",
                   "ct2_persistent_mode"}


def _mask_secret(value):
    if not isinstance(value, str) or not value:
        return value
    if len(value) <= 4:
        return "****"
    return "*" * (len(value) - 4) + value[-4:]


def display_key(value):
    """An API key as the frontend gets it: the first 3 and last 4 characters ("AQ.…k3Fz"), never the whole key.
    The frontend can call the backend from anything that reaches Decky's local websocket, so the keys stay here."""
    if not isinstance(value, str) or not value:
        return value
    if len(value) < 12:
        return "…" + value[-2:] if len(value) > 4 else "…"
    return f"{value[:3]}…{value[-4:]}"


def _mask_for_log(key, value):
    return _mask_secret(value) if key in SENSITIVE_SETTING_KEYS else value


_API_KEY_JUNK_RE = re.compile(r"[\s\u200b\u200c\u200d\u2060\ufeff]+")


def _clean_api_key(value):
    if not isinstance(value, str):
        return value
    return _API_KEY_JUNK_RE.sub("", value)


_URL_KEY_RE = re.compile(r"(?i)\b((?:api)?key=|bearer\s+|x-goog-api-key['\"]?:\s*['\"]?)([A-Za-z0-9_.\-]{16,})")


def _redact_url_keys(text):
    return _URL_KEY_RE.sub(lambda m: f"{m.group(1)}{_mask_secret(m.group(2))}", text)


def _may_hold_secret(text):
    low = text.lower()
    return "key" in low or "bearer" in low


class UrlKeyRedactFilter(logging.Filter):
    def filter(self, record):
        try:
            message = record.getMessage()  # msg % args, so a key passed as an argument is caught too
        except Exception:  # noqa: BLE001 - a broken format string: logging reports it itself
            return True
        if _may_hold_secret(message):
            record.msg, record.args = _redact_url_keys(message), None
        return True


_url_redact_filter = UrlKeyRedactFilter()


# Decky sets these for each plugin backend
settingsDir = decky.DECKY_PLUGIN_SETTINGS_DIR
logger = decky.logger
DECKY_PLUGIN_LOG_DIR = decky.DECKY_PLUGIN_LOG_DIR

# Ensure log directory exists
os.makedirs(DECKY_PLUGIN_LOG_DIR, exist_ok=True)

# Set up file logging
from logging.handlers import TimedRotatingFileHandler

log_file = Path(DECKY_PLUGIN_LOG_DIR) / "decky-translator.log"
log_file_handler = TimedRotatingFileHandler(log_file, when="midnight", backupCount=2, encoding="utf-8")
log_file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
log_file_handler.addFilter(_url_redact_filter)
logger.handlers.clear()
logger.addHandler(log_file_handler)
logger.setLevel(logging.INFO)
logging.getLogger("urllib3").addFilter(_url_redact_filter)
logger.info(f"Configured rotating log file: {log_file}")

try:
    with open(os.path.join(PLUGIN_DIR, "package.json"), encoding="utf-8") as _pkg:
        _plugin_version = json.load(_pkg).get("version", "unknown")
except (OSError, ValueError):
    _plugin_version = "unknown"
logger.info(f"WinDecky Translator v{_plugin_version} starting")


# The capture's name for the frontend (no file is written; suspended.json of winport/pause.py lives here too)
SCREENSHOT_DIR = os.path.join(tempfile.gettempdir(), "decky-translator")
# What keeps parts of the plugin from working, for the frontend to show (get_boot_status). Capture and overlay load
# compiled modules (winrt, Pillow) built for one Python version into Decky's own interpreter: after a Decky update
# that changes its Python they fail to import, and the rest of the plugin should still load and say why.
_BOOT_ERRORS = []
# Decky Loader for Windows: capture, hotkey, overlay and pause are in py_modules/winport
if sys.version_info[:2] != (3, 14):
    _BOOT_ERRORS.append(f"Decky Loader runs Python {sys.version_info[0]}.{sys.version_info[1]}, this build of the "
                        "plugin was made for 3.14: update the plugin")
try:
    from winport.capture import capture_foreground
except Exception as _e:  # noqa: BLE001 - ImportError, or OSError from a DLL that won't load
    capture_foreground = None
    _BOOT_ERRORS.append(f"Screen capture is unavailable: {_e}")
try:
    from winport.overlay import Overlay
except Exception as _e:  # noqa: BLE001
    Overlay = None
    _BOOT_ERRORS.append(f"The translation overlay is unavailable: {_e}")
from winport.hotkey import Hotkey  # ctypes only
try:
    from winport import pause as game_pause
except Exception as _e:  # noqa: BLE001
    game_pause = None
    _BOOT_ERRORS.append(f"Pause Game While Translating is unavailable: {_e}")
for _error in _BOOT_ERRORS:
    logger.error(_error)


# The plugin's errors as the frontend gets them, {error: code, message} (src/TextRecognizer.tsx throwIfBackendError)
_ERROR_CODES = ((NetworkError, "network_error"), (ApiKeyError, "api_key_error"), (RateLimitError, "rate_limit_error"),
                (OCRError, "ocr_failed"), (TranslationError, "translation_failed"))


def answers_errors(fallback_code, fallback_message):
    """A backend call whose failures reach the frontend as {error, message}: the plugin's own errors with their
    message, anything else (a bug) as fallback_code with fallback_message, logged with its traceback.

    A decorator: @answers_errors(...) above a method replaces it with call(), which runs the method inside the try."""
    def wrap(method):
        @functools.wraps(method)  # keeps the name Decky calls it by
        async def call(*args, **kwargs):
            try:
                return await method(*args, **kwargs)
            except tuple(cls for cls, _ in _ERROR_CODES) as e:
                code = next(code for cls, code in _ERROR_CODES if isinstance(e, cls))
                logger.error(f"{method.__name__}: {code}: {e}")
                return {"error": code, "message": str(e)}
            except Exception:
                logger.exception(method.__name__)
                return {"error": fallback_code, "message": fallback_message}
        return call
    return wrap


class SettingsManager:
    def __init__(self, name, settings_directory):
        self.settings_path = os.path.join(settings_directory, f"{name}.json")
        self.settings = {}
        logger.debug(f"SettingsManager initialized with path: {self.settings_path}")

    def read(self):
        try:
            if os.path.exists(self.settings_path):
                with open(self.settings_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                if not isinstance(loaded, dict):
                    raise ValueError("settings file is not a JSON object")
                self.settings = loaded
                logger.debug(f"Settings loaded from {self.settings_path}")
            else:
                logger.warning(f"Settings file does not exist: {self.settings_path}")
        except (ValueError, UnicodeDecodeError) as e:
            # damaged file (e.g. a write cut off by a crash): keep what is in memory, and keep the
            # damaged file aside instead of letting the next save replace it
            logger.error(f"Settings file is damaged ({e}); kept as {self.settings_path}.damaged")
            try:
                os.replace(self.settings_path, self.settings_path + ".damaged")
            except OSError:
                pass
        except Exception as e:
            logger.error(f"Failed to read settings: {str(e)}")
            logger.error(traceback.format_exc())

    def _write(self):
        """Write the settings atomically: a temporary file, flushed to disk, then renamed over the old one."""
        os.makedirs(os.path.dirname(self.settings_path), exist_ok=True)
        tmp = self.settings_path + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self.settings, f, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.settings_path)

    def set_setting(self, key, value):
        try:
            # re-read so manual edits to the file are not overwritten by stale memory
            self.read()
            self.settings[key] = value
            self._write()
            logger.debug(f"Saved setting {key}={_mask_for_log(key, value)}")
            return True
        except Exception as e:
            logger.error(f"Failed to save setting {key}: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    def get_setting(self, key, default=None):
        return self.settings.get(key, default)


class Plugin:
    _settings = None
    _pause_problems_shown: frozenset = frozenset()  # pause problems already shown to the user (_report_pause_problem)
    _provider_manager: ProviderManager = None

    # Windows: the translation overlay window, the window the last screenshot came from, the Ctrl+Alt+T hotkey
    _overlay = None
    _overlay_visible = False
    _capture_target = None
    _hotkey = None
    _loop = None

    _translation_cache: TranslationCache = None

    def _get(self, key):
        """A setting's current value (or its default from SETTING_DEFAULTS)."""
        return self._settings.get_setting(key, SETTING_DEFAULTS[key])

    async def set_setting(self, key, value):
        if key not in SETTING_DEFAULTS:
            logger.warning(f"Unknown setting {key}: not stored")
            return False
        if key in SENSITIVE_SETTING_KEYS and isinstance(value, str):
            if value and value == display_key(self._get(key) or ""):
                return True  # the frontend saved the key it was shown (a dialog closed without a new key): unchanged
            cleaned = _clean_api_key(value)
            if cleaned != value:
                logger.warning(f"{key} contained whitespace or invisible characters, "
                               f"cleaned (len {len(value)} -> {len(cleaned)})")
            value = cleaned
            logger.info(f"{key} set (len={len(value)})")
        logger.debug(f"Setting {key} to: {_mask_for_log(key, value)}")
        if not self._settings.set_setting(key, value):
            return False
        try:
            self._apply_setting(key)
        except Exception:  # noqa: BLE001 - stored; tell the frontend it didn't take effect
            logger.exception(f"Applying {key} failed")
            return False
        return True

    def _apply_setting(self, key):
        """What a changed setting changes in the backend now (the others are read where they are used)."""
        if key == "enabled":
            enabled = bool(self._get("enabled"))
            if not enabled:
                self._resume_paused_games()  # never leave a game frozen behind a switched-off plugin
            if self._hotkey:
                self._hotkey.set_enabled(enabled)
        if key == "debug_mode":
            logger.setLevel(logging.DEBUG if self._get("debug_mode") else logging.INFO)
        if key in PROVIDER_SETTINGS:
            self._configure_providers()
        if key in WORKER_SETTINGS:
            self._sync_workers()

    def _configure_providers(self):
        """Engine choice, keys and models -> the provider manager."""
        pm = self._provider_manager
        if not pm:
            return
        pm.configure(google_api_key=self._get("google_api_key"), gemini_api_key=self._get("gemini_api_key"),
                     ocr_provider=self._get("ocr_provider"), translation_provider=self._get("translation_provider"))
        pm.set_gemini_model(self._get("gemini_model"))
        pm.configure_llm(
            backend=self._get("llm_backend"),
            keys={"gemini": self._get("gemini_api_key"), "groq": self._get("groq_api_key"),
                  "custom": self._get("llm_custom_api_key")},
            models={"gemini": self._get("llm_gemini_model"), "groq": self._get("llm_groq_model"),
                    "custom": self._get("llm_custom_model")},
            custom_url=self._get("llm_custom_url"),
        )

    def _sync_workers(self):
        """The Screen AI and NLLB workers stay up between requests only while the plugin is on, their engine is the
        chosen one and its "Faster ..." setting is on; otherwise each request starts and stops its own."""
        pm = self._provider_manager
        if not pm:
            return
        on = bool(self._get("enabled"))
        pm.set_chromescreenai_persistent_mode(
            on and self._get("ocr_provider") == "chromescreenai" and bool(self._get("chromescreenai_persistent_mode")))
        pm.set_ct2_persistent_mode(
            on and self._get("translation_provider") == "ct2" and bool(self._get("ct2_persistent_mode")))

    async def get_all_settings(self):
        # no catch-all: a failure here rejects the frontend's call instead of answering {} (every setting unset)
        settings = {key: self._get(key) for key in SETTING_DEFAULTS}
        for k in SENSITIVE_SETTING_KEYS:
            settings[k] = display_key(settings[k])
        return settings

    async def get_llm_models(self, backend: str):
        """Models the configured key can use on that AI backend, for the model picker."""
        try:
            if not self._provider_manager:
                return []
            llm = self._provider_manager.get_llm_provider()
            return await llm.list_models(backend)
        except Exception as e:
            logger.error(f"Error fetching {backend} models: {e}")
            return []

    async def get_gemini_models(self):
        try:
            if not self._get("gemini_api_key"):
                return []
            gemini = self._provider_manager.get_ocr_provider() if (
                self._provider_manager and self._get("ocr_provider") == "gemini_vision"
            ) else None
            if not gemini:
                from providers.gemini_vision import GeminiVisionProvider
                gemini = GeminiVisionProvider(api_key=self._get("gemini_api_key"))
            return await gemini.list_available_models()
        except Exception as e:
            logger.error(f"Error fetching Gemini models: {e}")
            return []

    async def get_provider_status(self):
        try:
            if self._provider_manager:
                return self._provider_manager.get_provider_status()
            return {"error": "Provider manager not initialized"}
        except Exception as e:
            logger.error(f"Error getting provider status: {str(e)}")
            return {"error": str(e)}

    async def check_web_reachability(self):
        try:
            if self._provider_manager:
                return await self._provider_manager.check_web_reachability()
            return {"error": "Provider manager not initialized"}
        except Exception as e:
            logger.error(f"Error checking web reachability: {str(e)}")
            return {"error": str(e)}

    async def take_screenshot(self, app_name: str = ""):
        """Capture the foreground window (winport/capture.py) and remember where it is for the overlay."""
        global _processing_lock
        if _processing_lock:
            logger.info("Screenshot already in progress, skipping")
            raise RuntimeError("Screenshot already in progress")
        _processing_lock = True
        try:
            if capture_foreground is None:
                logger.error("Screen capture is unavailable (see the start of the log)")
                return {"path": ""}
            own = (self._overlay.hwnd,) if self._overlay and self._overlay.hwnd else ()
            cap = await capture_foreground(exclude=own)
            if cap is None:
                logger.error("No foreground window to capture")
                return {"path": ""}
            name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", app_name or "").strip()
            if not name or name.lower() == "null":
                name = "Decky-Screenshot"
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
            # The screenshot stays in memory: the frontend doesn't draw it (the overlay window does), so it only
            # gets a name for recognize_text_file, and no file is written and read back
            path = os.path.join(SCREENSHOT_DIR, f"{name}_{timestamp}.png")
            self._capture_target = {"hwnd": cap.hwnd, "left": cap.left, "top": cap.top,
                                    "width": cap.width, "height": cap.height, "png": cap.png, "image": cap.image,
                                    "path": path}
            return {"path": path}
        except Exception as e:
            logger.error(f"Screenshot error: {e}")
            logger.error(traceback.format_exc())
            return {"path": ""}
        finally:
            _processing_lock = False

    # Windows: the frontend sends upstream's overlay state on every change; winport/overlay.py draws it over the
    # captured window (Steam's UI can't sit over other windows on Windows)
    async def native_overlay_update(self, state):
        try:
            if Overlay is None:
                return False
            if self._overlay is None:
                self._overlay = Overlay(on_error=lambda error: self._emit(
                    "translator_problem", f"The translation overlay doesn't work: {error}"))
            visible = bool(state and state.get("visible"))
            appeared = visible and not self._overlay_visible
            self._overlay_visible = visible
            if visible:
                self._overlay.show(state, self._capture_target)
                if appeared and self._get("pause_game_on_overlay"):
                    self._pause_captured_game()
            else:
                self._overlay.hide()
                self._resume_paused_games()
                self._release_capture()
            return True
        except Exception as e:
            logger.error(f"native_overlay_update failed: {e}")
            return False

    def _release_capture(self):
        """Drop the capture's pixels (the PNG and the decoded frame, megabytes) once nothing needs them; the window
        position stays for get_windows_status."""
        if self._capture_target:
            self._capture_target.pop("png", None)
            self._capture_target.pop("image", None)

    # Windows: Pause Game While Translating. The game is paused when its translation appears (right after the capture,
    # so the screenshot shows it running) and everything paused is resumed when the translation is hidden, however
    # it was started (Ctrl+Alt+T, the side menu, a controller shortcut) and even if the game exited meanwhile.
    def _pause_captured_game(self):
        if not game_pause:
            return  # reported at start (_BOOT_ERRORS)
        pid = game_pause.game_pid((self._capture_target or {}).get("hwnd"))
        if not pid:
            self._report_pause_problem("Pause Game While Translating: this window isn't a game Steam started, "
                                       "so it keeps running")
        elif not game_pause.suspend(pid):
            self._report_pause_problem("Pause Game While Translating: Windows didn't let the plugin pause this game "
                                       "(details in the plugin log)")

    def _report_pause_problem(self, message):
        """A toast once per kind of problem, not on every translation."""
        logger.warning(message)
        if message not in self._pause_problems_shown:
            # a new set, assigned: a class attribute must not be changed in place (it would be shared)
            self._pause_problems_shown = self._pause_problems_shown | {message}
            self._emit("translator_problem", message)

    def _resume_paused_games(self):
        if game_pause and game_pause.any_suspended():
            game_pause.resume_all()

    # Windows: Ctrl+Alt+T in a game (hotkey thread) -> the frontend translates or dismisses (src/windows.ts)
    def _emit(self, event, *args):
        """Send an event to the frontend from any thread (the hotkey's)."""
        if self._loop:
            asyncio.run_coroutine_threadsafe(decky.emit(event, *args), self._loop)

    def _on_hotkey(self):
        # A paused game is resumed here too, not only when the frontend hides the translation: if Steam's UI hangs or
        # is gone, Ctrl+Alt+T still unfreezes the game
        if self._loop:
            self._loop.call_soon_threadsafe(self._resume_paused_games)
        self._emit("translator_hotkey")

    async def get_windows_ocr_languages(self):
        """Languages (plugin codes) whose Windows OCR pack is installed."""
        from providers.windows_ocr import WindowsOCRProvider
        return WindowsOCRProvider().get_supported_languages()

    async def get_clipboard_text(self):
        """Text on the Windows clipboard, for the Paste button of the key dialogs."""
        from winport import clipboard
        return clipboard.get_text()

    async def get_boot_status(self):
        """Problems found while the plugin loaded (see _BOOT_ERRORS) and a shortcut another program took; the
        frontend shows them once."""
        problems = list(_BOOT_ERRORS)
        hotkey = self._hotkey.status() if self._hotkey else None
        if hotkey and hotkey["error"]:
            problems.append(f"{hotkey['hotkey']} is taken by another program (error {hotkey['error']}): "
                            "close that program or change its shortcut, then switch the plugin off and on")
        return problems

    async def get_windows_status(self):
        """Diagnostics of the Windows parts: hotkey, overlay, last capture."""
        return {
            "hotkey": self._hotkey.status() if self._hotkey else None,
            "overlay_error": self._overlay.error if self._overlay else None,
            "capture": {k: v for k, v in (self._capture_target or {}).items() if k not in ("png", "image")},
        }

    @answers_errors("ocr_failed", "Text recognition failed (details in the plugin log)")
    async def recognize_text(self, image_data):
        """image_data: base64 (data: URL or plain) from the frontend, or the image bytes from the backend itself."""
        if not image_data:
            logger.error("Empty image data for text recognition")
            return []

        if isinstance(image_data, (bytes, bytearray)):
            image_bytes = bytes(image_data)
        else:
            if image_data.startswith('data:image'):
                image_data = image_data.split(',', 1)[1]
            image_bytes = base64.b64decode(image_data)

        if not self._provider_manager:
            logger.error("Provider manager not initialized")
            return []

        if self._get("ocr_provider") == "chromescreenai" and not self._provider_manager.model_installed("chromescreenai"):
            return {"error": "model_not_available", "message": "Chrome Screen AI engine not downloaded.\nDownload it in plugin settings"}

        if self._get("ocr_provider") == "windows_ocr" and self._get("input_language") not in ("", "auto"):
            from providers.windows_ocr import WindowsOCRProvider, plugin_code
            if plugin_code(self._get("input_language")) not in WindowsOCRProvider().get_supported_languages():
                from providers.gemini_vision import LANG_NAMES
                lang = LANG_NAMES.get(self._get("input_language"), self._get("input_language"))
                return {"error": "model_not_available",
                        "message": f"No Windows OCR language pack for {lang}.\n"
                                   "Add it in Windows Settings or use On-Device (Chrome)"}

        # If using Gemini Vision, set the target language before OCR
        # so it can translate in the same API call
        if self._get("ocr_provider") == "gemini_vision":
            self._provider_manager.set_gemini_target_language(self._get("target_language"))

        start_time = time.time()
        text_regions = await self._provider_manager.recognize_text(
            image_bytes,
            language=self._get("input_language")
        )
        logger.info(f"OCR completed in {time.time() - start_time:.2f}s, found {len(text_regions)} regions")

        return [region.to_dict() for region in text_regions]

    def _is_capture(self, image_path) -> bool:
        return bool(self._capture_target and image_path and image_path == self._capture_target.get("path"))

    async def discard_screenshot(self, image_path: str) -> bool:
        """Drop a capture the frontend won't recognize (the translation was cancelled after the capture)."""
        if not self._is_capture(image_path):
            return False
        self._release_capture()
        return True

    async def recognize_text_file(self, image_path: str):
        """OCR of the capture take_screenshot named image_path (it is in memory, not a file)."""
        if not self._is_capture(image_path):
            logger.error(f"Not the current capture: {image_path}")
            return []
        png = self._capture_target.pop("png", None)  # only OCR needs the PNG
        if png is None:
            logger.error("The capture was already recognized or discarded")
            return []
        return await self.recognize_text(png)

    @answers_errors("translation_failed", "Translation failed (details in the plugin log)")
    async def translate_text(self, text_regions, target_language=None, input_language=None):
        if not text_regions:
            return []

        target_lang = target_language or self._get("target_language")
        input_lang = input_language or self._get("input_language")

        if not self._provider_manager:
            logger.error("Provider manager not initialized")
            return None

        # If regions already have translatedText (e.g. from Gemini Vision),
        # skip the translation step entirely
        if all(r.get("translatedText") is not None for r in text_regions):
            logger.info(f"Translation skipped: {len(text_regions)} regions already translated by OCR provider")
            if (self._get("translation_cache_enabled") and self._translation_cache
                    and self._get("ocr_provider") == "gemini_vision"):
                pairs = [(r["text"], r["translatedText"]) for r in text_regions]
                if any(normalize(s) != normalize(t) for s, t in pairs):
                    await self._use_cache(
                        self._translation_cache.put_many,
                        pairs, input_lang, target_lang,
                        PROVIDER_TIERS.get("gemini_vision", 0), "gemini_vision",
                    )
            return text_regions

        # Check if CT2 provider has the needed models
        if self._get("translation_provider") == "ct2":
            provider = self._provider_manager.get_translation_provider()
            if provider and not provider.is_available(input_lang, target_lang):
                if input_lang == "auto":
                    return {"error": "model_not_available", "message": "Offline translation requires a specific source language. Select one in plugin settings"}
                return {"error": "model_not_available", "message": "Offline model not found. Download it in plugin settings"}

        # Only translate regions that don't already have translatedText
        texts_to_translate = [
            region["text"] for region in text_regions
            if region.get("translatedText") is None
        ]

        cache_on = self._get("translation_cache_enabled") and self._translation_cache is not None
        provider_tier = PROVIDER_TIERS.get(self._get("translation_provider"), 0)

        cached = {}
        if cache_on and texts_to_translate:
            cached = await self._use_cache(
                self._translation_cache.get_many,
                texts_to_translate, input_lang, target_lang, provider_tier,
            ) or {}

        if cache_on:
            to_request, seen = [], set()
            for t in texts_to_translate:
                if t not in cached and t not in seen:
                    seen.add(t)
                    to_request.append(t)
        else:
            to_request = texts_to_translate

        start_time = time.time()
        requested = await self._provider_manager.translate_text(
            to_request, source_lang=input_lang, target_lang=target_lang
        ) if to_request else []
        elapsed = time.time() - start_time
        logger.info(f"Translation completed in {elapsed:.2f}s, {len(to_request)} new / {len(cached)} cached")
        for i, (src, dst) in enumerate(zip(to_request, requested)):
            logger.debug(f"  [{i}] '{src}' -> '{dst}'")
        if to_request and all(t is None for t in requested):
            # nothing came back (the free services changed or refuse): say so instead of showing the originals
            raise TranslationError("The translation service did not answer (details in the plugin log)")

        # Failed items come back as None. The AI provider reports per item whether the AI or its Google/Bing
        # fallback translated it; each is cached under its own engine's tier.
        sources = getattr(requested, "sources", None)
        if not sources or len(sources) != len(to_request):
            sources = [self._get("translation_provider")] * len(to_request)
        by_source = {}
        for s, t, src in zip(to_request, requested, sources):
            if t is not None:
                by_source.setdefault(src or self._get("translation_provider"), []).append((s, t))
        for src, translated in by_source.items():
            if cache_on and any(normalize(s) != normalize(t) for s, t in translated):
                await self._use_cache(
                    self._translation_cache.put_many,
                    translated, input_lang, target_lang, PROVIDER_TIERS.get(src, provider_tier), src,
                )

        # A failed item shows its original text.
        result_map = {s: (t if t is not None else s) for s, t in zip(to_request, requested)}
        result_map.update(cached)

        translated_regions = []
        for region in text_regions:
            if region.get("translatedText") is not None:
                translated_regions.append(region)
            else:
                text = region["text"]
                translated_regions.append({
                    **region,
                    "translatedText": result_map.get(text, text)
                })

        logger.debug(f"Returning {len(translated_regions)} translated regions (from {len(text_regions)} input regions)")
        return translated_regions

    @staticmethod
    async def _use_cache(method, *args):
        """A translation cache call, off the event loop. A cache failure (a full disk, a locked or damaged database)
        costs only the cache, never the translation: None then."""
        try:
            return await asyncio.to_thread(method, *args)
        except sqlite3.Error as e:
            logger.error(f"Translation cache unavailable: {e}")
            return None

    async def clear_translation_cache(self):
        try:
            if not self._translation_cache:
                return {"success": False, "cleared": 0}
            cleared = await asyncio.to_thread(self._translation_cache.clear)
            return {"success": True, "cleared": cleared}
        except Exception as e:
            logger.error(f"Error clearing translation cache: {e}")
            return {"success": False, "error": str(e)}

    async def get_translation_cache_stats(self):
        try:
            if not self._translation_cache:
                return {"entries": 0, "hits": 0, "size_bytes": 0}
            return await asyncio.to_thread(self._translation_cache.stats)
        except Exception as e:
            logger.error(f"Error getting translation cache stats: {e}")
            return {"entries": 0, "hits": 0, "size_bytes": 0}

    async def get_translation_cache_entries(self, limit: int = 300):
        try:
            if not self._translation_cache:
                return []
            return await asyncio.to_thread(self._translation_cache.list_entries, limit)
        except Exception as e:
            logger.error(f"Error getting translation cache entries: {e}")
            return []

    async def delete_translation_cache_entry(self, source_lang, target_lang, source_text):
        try:
            if not self._translation_cache:
                return {"success": False}
            removed = await asyncio.to_thread(
                self._translation_cache.delete_entry, source_lang, target_lang, source_text
            )
            return {"success": True, "removed": removed}
        except Exception as e:
            logger.error(f"Error deleting translation cache entry: {e}")
            return {"success": False, "error": str(e)}

    # -- the downloadable models, by kind: "nllb" (offline translation) or "chromescreenai" (on-device OCR) --

    async def get_model_status(self, kind):
        """{downloaded, size, approx_size_mb, downloading, progress, error}, or None for an unknown kind."""
        return self._provider_manager.model_status(kind) if self._provider_manager else None

    async def download_model(self, kind):
        return bool(self._provider_manager and self._provider_manager.download_model(kind))

    async def cancel_model_download(self, kind):
        if self._provider_manager:
            self._provider_manager.cancel_model_download(kind)

    async def clear_model_error(self, kind):
        if self._provider_manager:
            self._provider_manager.clear_model_error(kind)

    async def delete_model(self, kind):
        return bool(self._provider_manager and self._provider_manager.delete_model(kind))

    def _start_windows(self):
        """Windows parts, first and each on its own: a failure anywhere else in the start must not leave a game paused
        by an earlier run or the shortcut dead."""
        try:
            if game_pause:
                game_pause.resume_leftovers()
        except Exception as e:
            logger.error(f"Could not resume games left paused: {e}")
        self._loop = asyncio.get_running_loop()
        try:
            self._hotkey = Hotkey(self._on_hotkey)
        except Exception as e:
            logger.error(f"Could not start the Ctrl+Alt+T hotkey: {e}")

    async def _main(self):
        logger.info("Plugin initialization started")
        self._start_windows()
        try:
            self._settings = SettingsManager(
                name="decky-translator-settings",
                settings_directory=settingsDir
            )
            self._settings.read()

            # Downloaded models (NLLB, Chrome Screen AI) live in the settings folder, so they survive plugin
            # updates
            models_dir = os.path.join(settingsDir, "decky-translator", "models")
            ct2_models_dir = os.path.join(models_dir, "nllb")
            os.makedirs(ct2_models_dir, exist_ok=True)

            try:
                self._translation_cache = TranslationCache(
                    os.path.join(settingsDir, "translation_cache.db")
                )
            except Exception as e:
                logger.error(f"Failed to open translation cache, continuing without it: {e}")
                self._translation_cache = None

            self._provider_manager = ProviderManager()
            self._provider_manager.configure(ct2_models_dir=ct2_models_dir, screenai_models_dir=models_dir)
            for key in ("debug_mode", "enabled"):  # log level; Ctrl+Alt+T on or off
                self._apply_setting(key)
            self._configure_providers()
            self._sync_workers()

            provider_status = self._provider_manager.get_provider_status()
            logger.info(f"Initialized - OCR: {provider_status.get('ocr_provider', '?')}, "
                        f"Translation: {provider_status.get('translation_provider', '?')}, "
                        f"Target lang: {self._get('target_language')}")

        except Exception as e:
            logger.error(f"Error during initialization: {e}")
            logger.error(traceback.format_exc())
        return

    async def _unload(self):
        logger.info("Unloading plugin")
        try:
            self._resume_paused_games()  # first: never leave a game paused

            if self._provider_manager:
                self._provider_manager.shutdown()
            await close_session()

            if self._translation_cache:
                self._translation_cache.close()
                self._translation_cache = None

            if self._overlay:
                self._overlay.stop()
                self._overlay = None

            if self._hotkey:
                self._hotkey.close()
                self._hotkey = None

        except Exception as e:
            logger.error(f"Error during plugin unload: {e}")
            logger.error(traceback.format_exc())
        return