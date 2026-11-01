"""API keys: where they show (masked in the log, shortened for the frontend) and how a pasted one is cleaned."""
import logging
import re

# The settings that hold API keys
SENSITIVE_SETTING_KEYS = {
    "groq_api_key",
    "llm_custom_api_key",
    "google_api_key",
    "gemini_api_key",
}


def mask_secret(value):
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


def mask_for_log(key, value):
    return mask_secret(value) if key in SENSITIVE_SETTING_KEYS else value


API_KEY_JUNK_RE = re.compile(r"[\s\u200b\u200c\u200d\u2060\ufeff]+")


def clean_api_key(value):
    if not isinstance(value, str):
        return value
    return API_KEY_JUNK_RE.sub("", value)


URL_KEY_RE = re.compile(r"(?i)\b((?:api)?key=|bearer\s+|x-goog-api-key['\"]?:\s*['\"]?)([A-Za-z0-9_.\-]{16,})")


def redact_url_keys(text):
    return URL_KEY_RE.sub(lambda m: f"{m.group(1)}{mask_secret(m.group(2))}", text)


def may_hold_secret(text):
    low = text.lower()
    return "key" in low or "bearer" in low


class UrlKeyRedactFilter(logging.Filter):
    def filter(self, record):
        try:
            message = record.getMessage()  # msg % args, so a key passed as an argument is caught too
        except Exception:  # noqa: BLE001 - a broken format string: logging reports it itself
            return True
        if may_hold_secret(message):
            record.msg, record.args = redact_url_keys(message), None
        return True
