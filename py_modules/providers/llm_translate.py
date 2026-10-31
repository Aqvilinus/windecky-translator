# providers/llm_translate.py
# AI translation: Gemini (Google AI Studio key) or an OpenAI-compatible API (Groq, or any custom endpoint such as
# OpenRouter or a local llama-server). The whole screen goes in one request, so every line is translated with the
# rest of the screen as context. Whatever the AI doesn't return (rate limit, network, a malformed reply) goes to the
# free Google -> Bing chain.

import json
import logging
import re
import time
from typing import Dict, List, Optional

from .base import (TranslationProvider, ProviderType, NetworkError, ApiKeyError, RateLimitError, Response,
                   chunk_indices, fetch, probe)
from . import gemini_api
from .free_translate import FreeTranslateProvider
from .gemini_vision import LANG_NAMES

logger = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1"

BACKENDS = ("gemini", "groq", "custom")
DEFAULT_MODELS = {
    "gemini": gemini_api.FALLBACK_MODEL,  # Google's alias for the current Flash-Lite; fixed names get retired
    "groq": "openai/gpt-oss-120b",
    "custom": "",
}

REQUEST_TIMEOUT = 20
BATCH_ITEMS = 80          # lines per request
BATCH_CHARS = 8000        # characters per request
RATE_LIMIT_PAUSE = 60     # seconds without the AI after a 429 that names no retry time
MAX_RATE_LIMIT_PAUSE = 15 * 60

# Which engine produced each result of the last batch (main.py caches AI and fallback results under their own tier)
SOURCE_LLM = "llm"
SOURCE_FALLBACK = "freegoogle"


class Translations(list):
    """The translations of a batch, plus which engine made each one (sources: SOURCE_LLM / SOURCE_FALLBACK / None),
    so main.py caches each under its own tier. Carried with the result: a field on the provider was overwritten by
    a batch that finished in between."""
    sources: List[Optional[str]] = []


def _lang_name(code: str) -> str:
    return LANG_NAMES.get(code, code)


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
        return min(MAX_RATE_LIMIT_PAUSE, float(resp.headers.get("retry-after", "")))
    except ValueError:
        pass
    # Gemini: {"error": {"details": [{"retryDelay": "31s"}]}}
    match = re.search(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', resp.text or "")
    return min(MAX_RATE_LIMIT_PAUSE, float(match.group(1))) if match else RATE_LIMIT_PAUSE


def _error_message(resp: Response) -> str:
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


class LLMTranslateProvider(TranslationProvider):
    """Translation with Gemini / Groq / an OpenAI-compatible API, the free Google -> Bing chain as fallback."""

    def __init__(self, fallback: Optional[FreeTranslateProvider] = None):
        self._fallback = fallback or FreeTranslateProvider()
        self._backend = "gemini"
        self._keys: Dict[str, str] = {"gemini": "", "groq": "", "custom": ""}
        self._models: Dict[str, str] = dict(DEFAULT_MODELS)
        self._custom_url = ""
        self._paused_until = 0.0
        self.last_error = ""

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
    def backend(self) -> str:
        return self._backend

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

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.LLM

    def is_available(self, source_lang: str, target_lang: str) -> bool:
        return True  # the fallback chain always is

    def get_supported_languages(self) -> List[str]:
        return list(LANG_NAMES.keys())

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
        return await fetch("POST", url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)

    def _check(self, resp: Response) -> None:
        if resp.status_code == 200:
            return
        message = _error_message(resp)
        if resp.status_code == 429:
            pause = _retry_after(resp)
            self._paused_until = time.time() + pause
            raise RateLimitError(f"AI rate limit, using Google/Bing for {int(pause)} s: {message}")
        if resp.status_code in (401, 403) or "API_KEY_INVALID" in message or "API key not valid" in message:
            raise ApiKeyError(f"{self.name}: invalid API key ({message})")
        raise NetworkError(f"{self.name} error {resp.status_code}: {message}")

    async def _gemini_request(self, system: str, user: str) -> str:
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "OBJECT",
                    "properties": {"translations": {"type": "ARRAY", "items": {"type": "STRING"}}},
                    "required": ["translations"],
                },
            },
        }
        # retired model -> current alias, thinking setting the model rejects -> less (gemini_api.generate)
        resp, _ = await gemini_api.generate(self._keys["gemini"], self.model, payload, REQUEST_TIMEOUT)
        self._check(resp)
        body = resp.json()
        usage = body.get("usageMetadata") or {}
        if usage:
            logger.debug(f"Gemini tokens: prompt={usage.get('promptTokenCount')}, "
                         f"output={usage.get('candidatesTokenCount')}")
        try:
            parts = body["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError):
            raise NetworkError(f"Gemini returned no text (blocked? {json.dumps(body)[:200]})")
        return "".join(p.get("text", "") for p in parts if not p.get("thought"))

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
                    + ("" if result else f", unusable reply: {reply[:200]!r}"))
        return result

    async def _translate_lines(self, texts: List[str], source_lang: str, target_lang: str) -> List[Optional[str]]:
        results: List[Optional[str]] = [None] * len(texts)
        sources: List[Optional[str]] = [None] * len(texts)
        order = [i for i, t in enumerate(texts) if t and t.strip()]
        chunks = chunk_indices(texts, BATCH_CHARS, max_items=BATCH_ITEMS)

        self.last_error = ""
        for chunk in chunks:
            if not self.is_configured() or time.time() < self._paused_until:
                break
            try:
                out = await self._translate_chunk([texts[i] for i in chunk], source_lang, target_lang)
            except ApiKeyError:
                raise
            except (RateLimitError, NetworkError) as e:
                self.last_error = str(e)
                logger.warning(f"{self.name}: {e}; Google/Bing translates the rest")
                break
            except Exception as e:
                self.last_error = str(e)
                logger.warning(f"{self.name} failed: {e}")
                break
            if out is None:
                continue
            for i, t in zip(chunk, out):
                if t.strip():
                    results[i], sources[i] = t.strip(), SOURCE_LLM

        missing = [i for i in order if results[i] is None]
        if missing:
            fallback = await self._fallback._translate_lines([texts[i] for i in missing],
                                                       self._fallback._map_language(source_lang),
                                                       self._fallback._map_language(target_lang))
            for i, t in zip(missing, fallback):
                results[i] = t
                if t is not None:
                    sources[i] = SOURCE_FALLBACK
        for i, t in enumerate(texts):
            if not t or not t.strip():
                results[i] = t
        out = Translations(results)
        out.sources = sources
        return out

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if not text or not text.strip():
            return text
        result = (await self._translate_lines([text], source_lang, target_lang))[0]
        return result if result is not None else text

    async def translate_batch(self, texts: List[str], source_lang: str, target_lang: str) -> List[Optional[str]]:
        if not texts:
            return texts
        return await self._translate_lines(list(texts), source_lang, target_lang)

    # -- settings UI helpers --

    async def list_models(self, backend: str) -> List[str]:
        """Models the key can use, for the model picker (text models only)."""
        try:
            if backend == "gemini":
                return await gemini_api.list_models(self._keys["gemini"])
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
            skip = ("whisper", "tts", "guard", "embed", "orpheus", "playai", "compound")
            names = [m.get("id", "") for m in resp.json().get("data", []) if m.get("active", True)]
            return sorted(n for n in names if n and not any(s in n.lower() for s in skip))
        except Exception as e:
            logger.warning(f"Listing {backend} models failed: {e}")
            return []

    async def test_network(self) -> tuple:
        if not self.is_configured():
            return False, "API key required" if self._backend != "custom" else "Server address and model required"

        # Reads the model's info (Gemini) or the model list: checks address and key without using request quota
        if self._backend == "gemini":
            resp, error = await probe("GET", f"{gemini_api.API_URL}/{self.model}",
                                      headers=gemini_api.headers(self._keys["gemini"]))
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
