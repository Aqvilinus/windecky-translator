"""The plugin's settings, the JSON file they are kept in, and how API keys are shown."""
import json
import logging
import os
import re

logger = logging.getLogger(__name__)

# set_setting stores only these keys
SETTING_DEFAULTS = {
    "enabled": True,
    "target_language": "en",
    "input_language": "auto",
    "ocr_provider": "chromescreenai",       # or "windows_ocr", "googlecloud", "gemini_vision"
    "translation_provider": "freegoogle",   # or "googlecloud", "ct2" (offline NLLB), "llm" (AI)
    "google_api_key": "",                   # one Google Cloud key for Vision and Translation
    "gemini_api_key": "",                   # Gemini Vision, and AI translation through Gemini
    "gemini_model": "gemini-3.5-flash",     # Gemini Vision's model
    "chromescreenai_persistent_mode": False,  # "Faster Recognition"
    "ct2_persistent_mode": False,
    "pause_game_on_overlay": False,
    "translation_cache_enabled": True,
    "debug_mode": False,
    # read by the frontend only
    "font_scale": 1.0,
    "confidence_threshold": 0.6,
    "custom_recognition_settings": False,
    # AI translation
    "llm_backend": "gemini",                # or "groq", "custom" (any OpenAI-compatible server)
    "llm_gemini_model": "gemini-flash-lite-latest",
    "llm_groq_model": "openai/gpt-oss-120b",
    "llm_custom_model": "",
    "llm_custom_url": "",                   # e.g. https://openrouter.ai/api/v1 or http://127.0.0.1:8081/v1
    "groq_api_key": "",
    "llm_custom_api_key": "",
}
PROVIDER_SETTINGS = {"ocr_provider", "translation_provider", "google_api_key", "gemini_api_key", "gemini_model",
                     "llm_backend", "llm_gemini_model", "llm_groq_model", "llm_custom_model", "llm_custom_url",
                     "groq_api_key", "llm_custom_api_key"}
WORKER_SETTINGS = {"enabled", "ocr_provider", "translation_provider", "chromescreenai_persistent_mode",
                   "ct2_persistent_mode"}
API_KEY_SETTINGS = {"google_api_key", "gemini_api_key", "groq_api_key", "llm_custom_api_key"}


class SettingsStore:
    def __init__(self, path):
        self.path = path
        self._values = {}

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                self._values = json.load(f)
        except FileNotFoundError:
            pass  # first start
        except ValueError as e:
            logger.error(f"Settings file unreadable ({e}): starting from the defaults")

    def get(self, key):
        return self._values.get(key, SETTING_DEFAULTS[key])

    def set(self, key, value) -> bool:
        self._values[key] = value
        try:
            self._save_atomically()
            return True
        except OSError:
            logger.exception(f"Could not save setting {key}")
            return False

    def _save_atomically(self):
        """A crash mid-write leaves the old file whole."""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._values, f, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)


# API keys are never shown whole: anything that reaches Decky's local websocket can call the backend.

def mask_key(value):
    """"AQ.…k3Fz": enough to recognise the key."""
    if not isinstance(value, str) or not value:
        return value
    if len(value) < 12:
        return "…" + value[-2:] if len(value) > 4 else "…"
    return f"{value[:3]}…{value[-4:]}"


_PASTE_JUNK_RE = re.compile(r"[\s​‌‍⁠﻿]+")


def clean_pasted_key(value):
    return _PASTE_JUNK_RE.sub("", value) if isinstance(value, str) else value


_KEY_IN_TEXT_RE = re.compile(r"(?i)\b((?:api)?key=|bearer\s+|x-goog-api-key['\"]?:\s*['\"]?)([A-Za-z0-9_.\-]{16,})")


class RedactKeysFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()  # msg % args: a key passed as an argument is caught too
        record.msg, record.args = _KEY_IN_TEXT_RE.sub(lambda m: m.group(1) + mask_key(m.group(2)), message), None
        return True
