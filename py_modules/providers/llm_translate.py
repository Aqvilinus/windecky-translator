"""AI translation: Gemini (Google AI Studio key) or an OpenAI-compatible API (Groq, or any custom endpoint such as
OpenRouter or a local llama-server). The whole screen goes in one request, so every line is translated with the
rest of the screen as context. Whatever the AI doesn't return (rate limit, network, a malformed reply) goes to the
free Google -> Bing chain."""

import json
import logging
import re
import time
from typing import Dict, List, Optional

from .base import (LANGUAGE_NAMES, TranslationProvider, NetworkError, ApiKeyError, RateLimitError, Response,
                   api_error, chunk_indices, error_message, fetch, probe)
from . import gemini_client
from .google_web_translate import GoogleWebTranslateProvider

logger = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1"

BACKENDS = ("gemini", "groq", "custom")
DEFAULT_MODELS = {
    "gemini": gemini_client.FALLBACK_MODEL,  # Google's alias for the current Flash-Lite; fixed names get retired
    "groq": "openai/gpt-oss-120b",
    "custom": "",
}

REQUEST_TIMEOUT_SECONDS = 20
MAX_TEXTS_PER_REQUEST = 80
MAX_CHARS_PER_REQUEST = 8000
RATE_LIMIT_PAUSE_SECONDS = 60  # without the AI, after a 429 that names no retry time
MAX_RATE_LIMIT_PAUSE_SECONDS = 15 * 60

# Gemini's reply: {"translations": [one string per text sent]}
TRANSLATIONS_SCHEMA = {
    "type": "OBJECT",
    "properties": {"translations": {"type": "ARRAY", "items": {"type": "STRING"}}},
    "required": ["translations"],
}

# Which engine produced each result of the last batch (main.py caches AI and fallback results under their own tier)
SOURCE_LLM = "llm"
SOURCE_FALLBACK = "freegoogle"


class Translations(list):
    """The translations of a batch, plus which engine made each one (sources: SOURCE_LLM / SOURCE_FALLBACK / None),
    so main.py caches each under its own tier. Carried with the result: a field on the provider was overwritten by
    a batch that finished in between."""
    sources: List[Optional[str]] = []


def _lang_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code)


def _system_prompt(source_lang: str, target_lang: str) -> str:
    src = "" if not source_lang or source_lang == "auto" else f" from {_lang_name(source_lang)}"
    tgt = _lang_name(target_lang)
    return (
        f"You translate text that OCR read from one video game screen{src} into {tgt}.\n"
        "The input is a JSON object {\"texts\": [...]}: the screen's text blocks in reading order. Use the whole "
        "screen as context (dialogue, menus, item names), but translate each block on its own.\n"
        "Rules:\n"
        f"- Reply with JSON {{\"translations\": [...]}}: exactly one {tgt} string per input block, same order.\n"
        "- Keep it natural and about as short as the original: it is drawn over the original text.\n"
        "- Keep names, numbers, units, placeholders, button names and line breaks.\n"
        "- Quietly fix obvious OCR mistakes (broken letters, missing spaces).\n"
        f"- A block that is already {tgt}, or is only numbers or symbols, stays unchanged.\n"
        "- No notes, no explanations, no romanization."
    )


def _parse_translations(text: str, expected: int) -> Optional[List[str]]:
    """The model's reply -> list of `expected` strings, or None."""
    if not text:
        return None
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    data = None
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if 0 <= start < end:
            try:
                data = json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                pass
    if isinstance(data, dict):
        data = data.get("translations")
    if not isinstance(data, list) or len(data) != expected:
        return None
    return [item if isinstance(item, str) else str(item) for item in data]


def _retry_after(resp: Response) -> float:
    try:
        return min(MAX_RATE_LIMIT_PAUSE_SECONDS, float(resp.headers.get("retry-after", "")))
    except ValueError:
        pass
    # Gemini: {"error": {"details": [{"retryDelay": "31s"}]}}
    match = re.search(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', resp.text or "")
    return min(MAX_RATE_LIMIT_PAUSE_SECONDS, float(match.group(1))) if match else RATE_LIMIT_PAUSE_SECONDS


class LLMTranslateProvider(TranslationProvider):
    """Translation with Gemini / Groq / an OpenAI-compatible API, the free Google -> Bing chain as fallback."""

    def __init__(self, fallback: Optional[GoogleWebTranslateProvider] = None):
        self._fallback = fallback or GoogleWebTranslateProvider()
        self._backend = "gemini"
        self._keys: Dict[str, str] = {"gemini": "", "groq": "", "custom": ""}
        self._models: Dict[str, str] = dict(DEFAULT_MODELS)
        self._custom_url = ""
        self._paused_until = 0.0

    # -- configuration --

    def configure(self, backend: str = "", keys: Optional[Dict[str, str]] = None,
                  models: Optional[Dict[str, str]] = None, custom_url: str = "") -> None:
        if backend in BACKENDS and backend != self._backend:
            self._backend = backend
            self._paused_until = 0.0
        for name, value in (keys or {}).items():
            if name in self._keys:
                self._keys[name] = value or ""
        for name, value in (models or {}).items():
            if name in self._models:
                self._models[name] = value or DEFAULT_MODELS[name]
        if custom_url is not None:
            self._custom_url = custom_url.strip().rstrip("/")

    @property
    def model(self) -> str:
        return self._models.get(self._backend) or DEFAULT_MODELS.get(self._backend, "")

    def is_configured(self) -> bool:
        if self._backend == "custom":
            return bool(self._custom_url and self.model)
        return bool(self._keys.get(self._backend))

    @property
    def name(self) -> str:
        return {"gemini": "AI (Gemini)", "groq": "AI (Groq)", "custom": "AI (Custom)"}.get(self._backend, "AI")

    def is_available(self, source_lang: str, target_lang: str) -> bool:
        return True  # the fallback chain always is

    # -- requests --

    def _openai_base(self) -> str:
        return GROQ_URL if self._backend == "groq" else self._custom_url

    def _openai_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        key = self._keys.get(self._backend)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    async def _post(self, url: str, payload: dict, headers: dict) -> Response:
        return await fetch("POST", url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    def _check(self, resp: Response) -> None:
        if resp.status_code == 429:  # Google/Bing translate while the AI service is paused
            pause = _retry_after(resp)
            self._paused_until = time.time() + pause
            raise RateLimitError(f"AI rate limit, using Google/Bing for {int(pause)} s: {error_message(resp)}")
        if resp.status_code != 200:
            raise api_error(resp, self.name)

    async def _gemini_request(self, system: str, user: str) -> str:
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
                "responseSchema": TRANSLATIONS_SCHEMA,
            },
        }
        # retired model -> current alias, thinking setting the model rejects -> less (gemini_client.generate)
        resp = await gemini_client.generate(self._keys["gemini"], self.model, payload, REQUEST_TIMEOUT_SECONDS)
        self._check(resp)
        return gemini_client.reply_text(resp)

    async def _openai_request(self, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
        }
        if self._backend == "groq" and "gpt-oss" in self.model:
            payload["reasoning_effort"] = "low"
        resp = await self._post(f"{self._openai_base()}/chat/completions", payload, self._openai_headers())
        if resp.status_code == 400 and "response_format" in resp.text:
            del payload["response_format"]  # servers without JSON mode; the prompt asks for JSON anyway
            resp = await self._post(f"{self._openai_base()}/chat/completions", payload, self._openai_headers())
        self._check(resp)
        try:
            return resp.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError, ValueError):
            raise NetworkError(f"{self.name} returned no text")

    async def _translate_chunk(self, texts: List[str], source_lang: str, target_lang: str) -> Optional[List[str]]:
        system = _system_prompt(source_lang, target_lang)
        user = json.dumps({"texts": texts}, ensure_ascii=False)
        start = time.time()
        reply = await (self._gemini_request if self._backend == "gemini" else self._openai_request)(system, user)
        result = _parse_translations(reply, len(texts))
        logger.info(f"{self.name} [{self.model}]: {len(texts)} texts in {time.time() - start:.2f}s"
                    + ("" if result else ", unusable reply"))
        if not result:
            logger.debug(f"{self.name} reply: {reply[:200]!r}")  # screen text: only with debug logging on
        return result

    async def translate_batch(self, texts: List[str], source_lang: str, target_lang: str) -> List[Optional[str]]:
        results: List[Optional[str]] = [None] * len(texts)
        sources: List[Optional[str]] = [None] * len(texts)
        chunks = chunk_indices(texts, MAX_CHARS_PER_REQUEST, max_items=MAX_TEXTS_PER_REQUEST)

        for chunk in chunks:
            if not self.is_configured() or time.time() < self._paused_until:
                break
            try:
                out = await self._translate_chunk([texts[i] for i in chunk], source_lang, target_lang)
            except ApiKeyError:
                raise
            except (RateLimitError, NetworkError) as e:
                logger.warning(f"{self.name}: {e}; Google/Bing translates the rest")
                break
            except Exception as e:
                logger.warning(f"{self.name} failed: {e}")
                break
            if out is None:
                continue
            for i, t in zip(chunk, out):
                if t.strip():
                    results[i], sources[i] = t.strip(), SOURCE_LLM

        missing = [i for i, r in enumerate(results) if r is None]
        if missing:
            fallback = await self._fallback.translate_batch([texts[i] for i in missing], source_lang, target_lang)
            for i, t in zip(missing, fallback):
                results[i] = t
                if t is not None:
                    sources[i] = SOURCE_FALLBACK
        out = Translations(results)
        out.sources = sources
        return out

    # -- settings UI helpers --

    async def list_models(self, backend: str) -> List[str]:
        """Models the key can use, for the model picker (text models only)."""
        try:
            if backend == "gemini":
                return await gemini_client.list_models(self._keys["gemini"])
            base = GROQ_URL if backend == "groq" else self._custom_url
            if not base:
                return []
            headers = {}
            key = self._keys.get(backend)
            if key:
                headers["Authorization"] = f"Bearer {key}"
            resp = await fetch("GET", f"{base}/models", headers=headers)
            if resp.status_code != 200:
                return []
            not_text_model_markers = ("whisper", "tts", "guard", "embed", "orpheus", "playai", "compound")
            names = [m.get("id", "") for m in resp.json().get("data", []) if m.get("active", True)]
            return sorted(n for n in names if n and not any(s in n.lower() for s in not_text_model_markers))
        except Exception as e:
            logger.warning(f"Listing {backend} models failed: {e}")
            return []

    async def test_network(self) -> tuple:
        if not self.is_configured():
            return False, "API key required" if self._backend != "custom" else "Server address and model required"

        # Reads the model's info (Gemini) or the model list: checks address and key without using request quota
        if self._backend == "gemini":
            resp, error = await probe("GET", f"{gemini_client.API_URL}/{self.model}",
                                      headers=gemini_client.headers(self._keys["gemini"]))
        else:
            resp, error = await probe("GET", f"{self._openai_base()}/models", headers=self._openai_headers())
        if resp is None:
            return False, error
        if resp.status_code == 200:
            return True, ""
        if resp.status_code == 404 and self._backend == "gemini":
            return False, f"Unknown model {self.model}"
        if resp.status_code in (400, 401, 403):
            return False, "Invalid API key"
        if resp.status_code == 429:
            return False, "Rate limited"
        return False, f"API error ({resp.status_code})"
