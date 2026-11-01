"""The plugin's settings: every key with its default, and how API keys are shown. Decky's SettingsManager
stores them (main.py). Not named settings.py: Decky registers its own settings module under that name
before the plugin loads, so a plugin's settings.py would never be imported."""
import logging
import re

# set_setting stores only these keys
SETTING_DEFAULTS = {
    "enabled": True,
    "target_language": "en",
    "source_language": "auto",
    "ocr_provider": "chrome_screen_ai",       # or "windows_ocr", "google_cloud", "gemini_vision"
    "translation_provider": "google_web",   # or "google_cloud", "nllb" (offline), "llm" (AI)
    "google_api_key": "",                   # one Google Cloud key for Vision and Translation
    "gemini_api_key": "",                   # Gemini Vision, and AI translation through Gemini
    "gemini_model": "gemini-3.5-flash",     # Gemini Vision's model
    "chrome_screen_ai_keep_alive": False,  # "Faster Recognition"
    "nllb_keep_alive": False,
    "pause_game_on_overlay": False,
    "translation_cache_enabled": True,
    "debug_mode": False,
    "confidence_threshold": 0.6,            # OCR lines the engine is less sure of are dropped
    "font_scale": 1.0,                      # read by the frontend only
    "llm_service": "gemini",                # or "groq", "custom" (any OpenAI-compatible server)
    "llm_gemini_model": "gemini-flash-lite-latest",
    "llm_groq_model": "openai/gpt-oss-120b",
    "llm_custom_model": "",
    "llm_custom_url": "",                   # e.g. https://openrouter.ai/api/v1 or http://127.0.0.1:8081/v1
    "groq_api_key": "",
    "llm_custom_api_key": "",
}
PROVIDER_SETTINGS = {"ocr_provider", "translation_provider", "google_api_key", "gemini_api_key", "gemini_model",
                     "llm_service", "llm_gemini_model", "llm_groq_model", "llm_custom_model", "llm_custom_url",
                     "groq_api_key", "llm_custom_api_key"}
WORKER_SETTINGS = {"enabled", "ocr_provider", "translation_provider", "chrome_screen_ai_keep_alive",
                   "nllb_keep_alive"}
API_KEY_SETTINGS = {"google_api_key", "gemini_api_key", "groq_api_key", "llm_custom_api_key"}


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
