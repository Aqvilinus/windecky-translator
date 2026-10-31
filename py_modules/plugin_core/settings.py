"""The plugin's settings: every key with its default, and the JSON file they are kept in."""
import json
import logging
import os

from .secrets import mask_for_log

logger = logging.getLogger(__name__)

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
        except Exception:  # noqa: BLE001 - the plugin keeps running on the settings in memory
            logger.exception("Failed to read settings")

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
            logger.debug(f"Saved setting {key}={mask_for_log(key, value)}")
            return True
        except Exception:  # noqa: BLE001 - the frontend tells the user the setting wasn't saved
            logger.exception(f"Failed to save setting {key}")
            return False

    def get_setting(self, key, default=None):
        return self.settings.get(key, default)
