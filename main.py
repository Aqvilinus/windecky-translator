import asyncio
import functools
import os
import sys
import shutil
import traceback
import time
import logging
import sqlite3
import tarfile

import decky  # Decky Loader's plugin API (typings/decky.pyi)

PLUGIN_DIR = decky.DECKY_PLUGIN_DIR

# Decky downloads the third-party packages (package.json remote_binary, filled by scripts/build_windows.py) into bin/
# as one archive and doesn't unpack it. Every install and update starts from an empty bin/.
BIN_DIR = os.path.join(PLUGIN_DIR, "bin")
DEPENDENCIES_ARCHIVE = os.path.join(BIN_DIR, "plugin-dependencies.tar.gz")
# The archive holds py_modules (cp314 wheels) and python314 (the workers' interpreter)
BIN_PY_MODULES_DIR = os.path.join(BIN_DIR, "py_modules")
BIN_PYTHON_DIR = os.path.join(BIN_DIR, "python314")

if os.path.exists(DEPENDENCIES_ARCHIVE) and not os.path.isdir(BIN_PY_MODULES_DIR):
    staging = os.path.join(BIN_DIR, "extracting")  # a start cut short leaves no half-extracted packages in place
    try:
        decky.logger.info(f"Extracting {DEPENDENCIES_ARCHIVE}")
        for leftover in (staging, BIN_PYTHON_DIR):
            shutil.rmtree(leftover, ignore_errors=True)
        with tarfile.open(DEPENDENCIES_ARCHIVE, "r:gz") as tar:
            tar.extractall(path=staging, filter="data")  # no links or paths out of staging (3.14's default too)
        os.replace(os.path.join(staging, "python314"), BIN_PYTHON_DIR)
        os.replace(os.path.join(staging, "py_modules"), BIN_PY_MODULES_DIR)  # last: it marks a finished extraction
        os.rmdir(staging)
    except Exception as e:  # noqa: BLE001 - e.g. a full disk: the parts that need the packages report it
        decky.logger.error(f"Could not extract the dependencies: {e}")

# Decky puts the plugin's own py_modules on sys.path; the extracted third-party packages are ours to add
if os.path.exists(BIN_PY_MODULES_DIR) and BIN_PY_MODULES_DIR not in sys.path:
    sys.path.insert(0, BIN_PY_MODULES_DIR)

# Decky's frozen Python has python314.dll but not python3.dll, which stable-ABI extensions (psutil) load: the bundled
# runtime has it
if os.path.isdir(os.path.join(BIN_PYTHON_DIR, "python")):
    os.add_dll_directory(os.path.join(BIN_PYTHON_DIR, "python"))

from providers import ProviderRegistry
from providers.base import ApiKeyError, NetworkError, OCRError, RateLimitError, TranslationError, close_session
from providers.translation_cache import TranslationCache, PROVIDER_TIERS, normalize
from settings import SettingsManager  # Decky's own: decky_loader.settings, registered as settings for plugins
from plugin_settings import (API_KEY_SETTINGS, PROVIDER_SETTINGS, SETTING_DEFAULTS, WORKER_SETTINGS, RedactKeysFilter,
                             clean_pasted_key, mask_key)


SETTINGS_DIR = decky.DECKY_PLUGIN_SETTINGS_DIR
RUNTIME_DIR = decky.DECKY_PLUGIN_RUNTIME_DIR  # data, not configuration: downloaded models, the translation cache
# The root logger: Decky writes it to a new file in the plugin's log folder on every start and keeps the last 4
logger = decky.logger
for _handler in logger.handlers:
    _handler.addFilter(RedactKeysFilter())  # a handler filter also sees the providers' records, a logger filter not
logger.setLevel(logging.INFO)

logger.info(f"WinDecky Translator v{decky.DECKY_PLUGIN_VERSION} starting")


# What keeps parts of the plugin from working, for the frontend to show (get_startup_errors). Capture and overlay load
# compiled modules (winrt, Pillow) built for one Python version into Decky's own interpreter: after a Decky update
# that changes its Python they fail to import, and the rest of the plugin should still load and say why.
STARTUP_ERRORS = []
if sys.version_info[:2] != (3, 14):
    STARTUP_ERRORS.append(f"Decky Loader runs Python {sys.version_info[0]}.{sys.version_info[1]}, this build of the "
                        "plugin was made for 3.14: update the plugin")
try:
    from windows.capture import capture_foreground, encode_png
except Exception as _e:  # noqa: BLE001 - ImportError, or OSError from a DLL that won't load
    capture_foreground = encode_png = None
    STARTUP_ERRORS.append(f"Screen capture is unavailable: {_e}")
try:
    from windows.overlay_window import OverlayWindow
except Exception as _e:  # noqa: BLE001
    OverlayWindow = None
    STARTUP_ERRORS.append(f"The translation overlay is unavailable: {_e}")
from windows.hotkey import Hotkey  # ctypes only
try:
    import game_process
except Exception as _e:  # noqa: BLE001
    game_process = None
    STARTUP_ERRORS.append(f"Pause Game While Translating is unavailable: {_e}")
for _error in STARTUP_ERRORS:
    logger.error(_error)


# The plugin's errors as the frontend gets them, {error: code, message} (src/TextRecognizer.tsx throwIfBackendError)
_ERROR_CODES = ((NetworkError, "network_error"), (ApiKeyError, "api_key_error"), (RateLimitError, "rate_limit_error"),
                (OCRError, "ocr_failed"), (TranslationError, "translation_failed"))


def catch_errors(fallback_code, fallback_message):
    """A backend call whose failures reach the frontend as {error, message}: the plugin's own errors with their
    message, anything else (a bug) as fallback_code with fallback_message, logged with its traceback."""
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


class Plugin:
    _settings = None
    _pause_problems_shown: frozenset = frozenset()  # pause problems already shown to the user (_report_pause_problem)
    _providers: ProviderRegistry = None

    _overlay = None
    _overlay_visible = False
    _capturing = False
    _capture = None  # the last capture: the window it came from (for the overlay) and its pixels until OCR
    _capture_id = 0
    _hotkey = None
    _loop = None

    _translation_cache: TranslationCache = None

    def _setting(self, key):
        return self._settings.getSetting(key, SETTING_DEFAULTS[key])

    async def set_setting(self, key, value):
        if key not in SETTING_DEFAULTS:
            logger.warning(f"Unknown setting {key}: not stored")
            return False
        if key in API_KEY_SETTINGS and isinstance(value, str):
            if value and value == mask_key(self._setting(key) or ""):
                return True  # a key dialog closed without a new key saves back the masked one
            cleaned = clean_pasted_key(value)
            if cleaned != value:
                logger.warning(f"{key} contained whitespace or invisible characters, "
                               f"cleaned (len {len(value)} -> {len(cleaned)})")
            value = cleaned
            logger.info(f"{key} set (len={len(value)})")
        logger.debug(f"Setting {key} to: {mask_key(value) if key in API_KEY_SETTINGS else value}")
        try:
            self._settings.setSetting(key, value)
        except OSError:
            logger.exception(f"Could not save setting {key}")
            return False
        try:
            self._on_setting_changed(key)
        except Exception:  # noqa: BLE001 - stored; tell the frontend it didn't take effect
            logger.exception(f"Applying {key} failed")
            return False
        return True

    def _on_setting_changed(self, key):
        """What a changed setting changes in the backend now (the others are read where they are used)."""
        if key == "enabled":
            enabled = bool(self._setting("enabled"))
            if not enabled:
                self._resume_paused_games()  # never leave a game frozen behind a switched-off plugin
            if self._hotkey:
                self._hotkey.set_enabled(enabled)
        if key == "debug_mode":
            logger.setLevel(logging.DEBUG if self._setting("debug_mode") else logging.INFO)
        if key in PROVIDER_SETTINGS:
            self._configure_providers()
        if key in WORKER_SETTINGS:
            self._update_workers()

    def _configure_providers(self):
        pm = self._providers
        if not pm:
            return
        pm.configure(google_api_key=self._setting("google_api_key"), gemini_api_key=self._setting("gemini_api_key"),
                     ocr_provider=self._setting("ocr_provider"), translation_provider=self._setting("translation_provider"))
        pm.set_gemini_model(self._setting("gemini_model"))
        pm.configure_llm(
            backend=self._setting("llm_backend"),
            keys={"gemini": self._setting("gemini_api_key"), "groq": self._setting("groq_api_key"),
                  "custom": self._setting("llm_custom_api_key")},
            models={"gemini": self._setting("llm_gemini_model"), "groq": self._setting("llm_groq_model"),
                    "custom": self._setting("llm_custom_model")},
            custom_url=self._setting("llm_custom_url"),
        )

    def _update_workers(self):
        """The Screen AI and NLLB workers stay up between requests only while the plugin is on, their engine is the
        chosen one and its "Faster ..." setting is on; otherwise each request starts and stops its own."""
        pm = self._providers
        if not pm:
            return
        on = bool(self._setting("enabled"))
        pm.set_chromescreenai_persistent_mode(
            on and self._setting("ocr_provider") == "chromescreenai" and bool(self._setting("chromescreenai_persistent_mode")))
        pm.set_ct2_persistent_mode(
            on and self._setting("translation_provider") == "ct2" and bool(self._setting("ct2_persistent_mode")))

    async def get_all_settings(self):
        # no catch-all: a failure here rejects the frontend's call instead of answering {} (every setting unset)
        settings = {key: self._setting(key) for key in SETTING_DEFAULTS}
        for k in API_KEY_SETTINGS:
            settings[k] = mask_key(settings[k])
        return settings

    async def get_llm_models(self, backend: str):
        try:
            if not self._providers:
                return []
            llm = self._providers.get_llm_provider()
            return await llm.list_models(backend)
        except Exception as e:
            logger.error(f"Error fetching {backend} models: {e}")
            return []

    async def get_gemini_models(self):
        try:
            if not self._setting("gemini_api_key"):
                return []
            gemini = self._providers.get_ocr_provider() if (
                self._providers and self._setting("ocr_provider") == "gemini_vision"
            ) else None
            if not gemini:
                from providers.gemini_vision import GeminiVisionProvider
                gemini = GeminiVisionProvider(api_key=self._setting("gemini_api_key"))
            return await gemini.list_available_models()
        except Exception as e:
            logger.error(f"Error fetching Gemini models: {e}")
            return []

    async def check_web_reachability(self):
        try:
            if self._providers:
                return await self._providers.check_web_reachability()
            return {"error": "Provider manager not initialized"}
        except Exception as e:
            logger.error(f"Error checking web reachability: {str(e)}")
            return {"error": str(e)}

    async def capture_screen(self):
        """{"id": n} for recognize_capture, or {"error": why nothing was captured}. The pixels stay here: the
        overlay window, not the frontend, shows them."""
        if self._capturing:
            return {"error": "A capture is already running"}
        self._capturing = True
        try:
            if capture_foreground is None:
                return {"error": "Screen capture is unavailable: see the plugin's start-up message"}
            cap = await capture_foreground()
            if cap is None:
                return {"error": "No game window in front to capture"}
            self._capture_id += 1
            self._capture = {"id": self._capture_id, "hwnd": cap.hwnd, "left": cap.left, "top": cap.top,
                             "width": cap.width, "height": cap.height, "image": cap.image, "ocr_pending": True}
            return {"id": self._capture_id}
        except Exception as e:  # noqa: BLE001 - reported to the user, details in the log
            logger.exception("Screenshot error")
            return {"error": f"Screen capture failed: {e}"}
        finally:
            self._capturing = False

    # Windows: the frontend sends upstream's overlay state on every change; overlay.py draws it over the
    # captured window (Steam's UI can't sit over other windows on Windows)
    async def update_overlay(self, state):
        try:
            if OverlayWindow is None:
                return False
            if self._overlay is None:
                self._overlay = OverlayWindow()
            visible = bool(state and state.get("visible"))
            appeared = visible and not self._overlay_visible
            self._overlay_visible = visible
            if visible:
                self._overlay.show(state, self._capture)
                if appeared and self._setting("pause_game_on_overlay"):
                    self._pause_captured_game()
            else:
                self._overlay.hide()
                self._resume_paused_games()
                self._free_capture_image()
            return True
        except Exception as e:
            logger.error(f"update_overlay failed: {e}")
            return False

    def _free_capture_image(self):
        """Drop the capture's pixels (megabytes) once nothing needs them; the window position stays for
        get_diagnostics."""
        if self._capture:
            self._capture.pop("image", None)
            self._capture.pop("ocr_pending", None)

    # Windows: Pause Game While Translating. The game is paused when its translation appears (right after the capture,
    # so the screenshot shows it running) and everything paused is resumed when the translation is hidden, however
    # it was started (Ctrl+Alt+T, the side menu, a controller shortcut) and even if the game exited meanwhile.
    def _pause_captured_game(self):
        if not game_process:
            return  # reported at start (STARTUP_ERRORS)
        try:
            game_process.suspend((self._capture or {}).get("hwnd"))
        except game_process.SuspendError as e:
            self._report_pause_problem(f"Pause Game While Translating: {e}")

    def _report_pause_problem(self, message):
        """A toast once per kind of problem, not on every translation."""
        logger.warning(message)
        if message not in self._pause_problems_shown:
            # a new set, assigned: a class attribute must not be changed in place (it would be shared)
            self._pause_problems_shown = self._pause_problems_shown | {message}
            self._emit("translator_problem", message)

    def _resume_paused_games(self):
        if game_process:
            game_process.resume_all()

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
        from windows import clipboard
        return clipboard.get_text()

    async def get_startup_errors(self):
        """Problems found while the plugin loaded (see STARTUP_ERRORS) and a shortcut another program took; the
        frontend shows them once."""
        problems = list(STARTUP_ERRORS)
        hotkey = self._hotkey.status() if self._hotkey else None
        if hotkey and hotkey["error"]:
            problems.append(f"{hotkey['hotkey']} is taken by another program (error {hotkey['error']}): "
                            "close that program or change its shortcut, then switch the plugin off and on")
        return problems

    async def get_diagnostics(self):
        return {
            "hotkey": self._hotkey.status() if self._hotkey else None,
            "overlay_error": self._overlay.error if self._overlay else None,
            "capture": {k: v for k, v in (self._capture or {}).items() if k != "image"},
        }

    async def _recognize(self, png: bytes):
        if not self._providers:
            logger.error("Provider manager not initialized")
            return []

        if self._setting("ocr_provider") == "chromescreenai" and not self._providers.model_installed("chromescreenai"):
            return {"error": "model_not_available", "message": "Chrome Screen AI engine not downloaded.\nDownload it in plugin settings"}

        if self._setting("ocr_provider") == "windows_ocr" and self._setting("input_language") not in ("", "auto"):
            from providers.windows_ocr import WindowsOCRProvider, plugin_code
            if plugin_code(self._setting("input_language")) not in WindowsOCRProvider().get_supported_languages():
                from providers.gemini_vision import LANG_NAMES
                lang = LANG_NAMES.get(self._setting("input_language"), self._setting("input_language"))
                return {"error": "model_not_available",
                        "message": f"No Windows OCR language pack for {lang}.\n"
                                   "Add it in Windows Settings or use On-Device (Chrome)"}

        # Gemini Vision translates in the same call
        if self._setting("ocr_provider") == "gemini_vision":
            self._providers.set_gemini_target_language(self._setting("target_language"))

        start_time = time.time()
        text_regions = await self._providers.recognize_text(
            png, self._setting("input_language"), self._setting("confidence_threshold"))
        logger.info(f"OCR completed in {time.time() - start_time:.2f}s, found {len(text_regions)} regions")

        return [region.to_dict() for region in text_regions]

    def _is_current_capture(self, capture_id) -> bool:
        return bool(self._capture and capture_id and capture_id == self._capture.get("id"))

    async def discard_capture(self, capture_id: int) -> bool:
        """The translation was cancelled after the capture: its pixels go."""
        if not self._is_current_capture(capture_id):
            return False
        self._free_capture_image()
        return True

    @catch_errors("ocr_failed", "Text recognition failed (details in the plugin log)")
    async def recognize_capture(self, capture_id: int):
        if not self._is_current_capture(capture_id):
            logger.error(f"Not the current capture: {capture_id}")
            return []
        image = self._capture.get("image")
        if image is None or not self._capture.pop("ocr_pending", False):
            logger.error("The capture was already recognized or discarded")
            return []
        return await self._recognize(await asyncio.to_thread(encode_png, image))

    @catch_errors("translation_failed", "Translation failed (details in the plugin log)")
    async def translate_text(self, text_regions, target_lang, input_lang):
        if not text_regions:
            return []

        if not self._providers:
            logger.error("Provider manager not initialized")
            return None

        if all(r.get("translatedText") is not None for r in text_regions):
            logger.info(f"Translation skipped: {len(text_regions)} regions already translated by OCR provider")
            if (self._setting("translation_cache_enabled") and self._translation_cache
                    and self._setting("ocr_provider") == "gemini_vision"):
                pairs = [(r["text"], r["translatedText"]) for r in text_regions]
                if any(normalize(s) != normalize(t) for s, t in pairs):
                    await self._use_cache(
                        self._translation_cache.put_many,
                        pairs, input_lang, target_lang,
                        PROVIDER_TIERS.get("gemini_vision", 0), "gemini_vision",
                    )
            return text_regions

        if self._setting("translation_provider") == "ct2":
            provider = self._providers.get_translation_provider()
            if provider and not provider.is_available(input_lang, target_lang):
                if input_lang == "auto":
                    return {"error": "model_not_available", "message": "Offline translation requires a specific source language. Select one in plugin settings"}
                return {"error": "model_not_available", "message": "Offline model not found. Download it in plugin settings"}

        texts_to_translate = [
            region["text"] for region in text_regions
            if region.get("translatedText") is None
        ]

        cache_on = self._setting("translation_cache_enabled") and self._translation_cache is not None
        provider_tier = PROVIDER_TIERS.get(self._setting("translation_provider"), 0)

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
        requested = await self._providers.translate_text(
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
            sources = [self._setting("translation_provider")] * len(to_request)
        by_source = {}
        for s, t, src in zip(to_request, requested, sources):
            if t is not None:
                by_source.setdefault(src or self._setting("translation_provider"), []).append((s, t))
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

    async def count_translation_cache_entries(self) -> int:
        return await asyncio.to_thread(self._translation_cache.count)

    async def get_translation_cache_entries(self, limit: int):
        return await asyncio.to_thread(self._translation_cache.list_entries, limit)

    async def delete_translation_cache_entry(self, source_lang, target_lang, source_text):
        await asyncio.to_thread(self._translation_cache.delete_entry, source_lang, target_lang, source_text)

    async def clear_translation_cache(self):
        await asyncio.to_thread(self._translation_cache.clear)

    # -- the downloadable models, by kind: "nllb" (offline translation) or "chromescreenai" (on-device OCR) --

    async def get_model_status(self, kind):
        """{downloaded, size, approx_size_mb, downloading, progress, error}, or None for an unknown kind."""
        return self._providers.model_status(kind) if self._providers else None

    async def download_model(self, kind):
        return bool(self._providers and self._providers.download_model(kind))

    async def cancel_model_download(self, kind):
        if self._providers:
            self._providers.cancel_model_download(kind)

    async def clear_model_error(self, kind):
        if self._providers:
            self._providers.clear_model_error(kind)

    async def delete_model(self, kind):
        return bool(self._providers and self._providers.delete_model(kind))

    def _start_windows_integration(self):
        """Windows parts, first and each on its own: a failure anywhere else in the start must not leave a game paused
        by an earlier run or the shortcut dead."""
        try:
            if game_process:
                game_process.resume_after_restart()
        except Exception as e:
            logger.error(f"Could not resume games left paused: {e}")
        self._loop = asyncio.get_running_loop()
        try:
            self._hotkey = Hotkey(self._on_hotkey)
        except Exception as e:
            logger.error(f"Could not start the Ctrl+Alt+T hotkey: {e}")

    async def _main(self):
        logger.info("Plugin initialization started")
        self._start_windows_integration()
        try:
            self._settings = SettingsManager(name="decky-translator-settings", settings_directory=SETTINGS_DIR)

            models_dir = os.path.join(RUNTIME_DIR, "models")
            ct2_models_dir = os.path.join(models_dir, "nllb")
            os.makedirs(ct2_models_dir, exist_ok=True)

            try:
                self._translation_cache = TranslationCache(os.path.join(RUNTIME_DIR, "translation_cache.db"))
            except Exception as e:
                logger.error(f"Failed to open translation cache, continuing without it: {e}")
                self._translation_cache = None

            self._providers = ProviderRegistry()
            self._providers.configure(ct2_models_dir=ct2_models_dir, screenai_models_dir=models_dir)
            for key in ("debug_mode", "enabled"):  # log level; Ctrl+Alt+T on or off
                self._on_setting_changed(key)
            self._configure_providers()
            self._update_workers()

            logger.info(f"Initialized - OCR: {self._setting('ocr_provider')}, "
                        f"Translation: {self._setting('translation_provider')}, "
                        f"Target lang: {self._setting('target_language')}")

        except Exception as e:
            logger.error(f"Error during initialization: {e}")
            logger.error(traceback.format_exc())
        return

    async def _unload(self):
        logger.info("Unloading plugin")
        try:
            self._resume_paused_games()  # first: never leave a game paused
            if self._hotkey:
                self._hotkey.close()
            if self._overlay:
                self._overlay.stop()
            if self._providers:
                self._providers.shutdown()
            if self._translation_cache:
                self._translation_cache.close()
            await close_session()
        except Exception:  # noqa: BLE001
            logger.exception("Error during plugin unload")
