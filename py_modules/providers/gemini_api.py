# providers/gemini_api.py
# Google's Gemini REST API, shared by Gemini Vision (OCR + translation, gemini_vision.py) and AI translation
# (llm_translate.py): the address, the key header, the model list, and the retries a request may need.
#
# Models get retired ("no longer available to new users": 404) and newer ones reject settings older ones need (a
# thinking budget of 0 -> 400). generate() retries such a request once with Google's current-model alias, and with the
# least thinking, then none. What it learns is kept for the session, so the next requests go straight to what works.

import logging
from typing import Dict, List, Optional, Tuple

from .base import NetworkError, Response, fetch

logger = logging.getLogger(__name__)

API_URL = "https://generativelanguage.googleapis.com/v1beta/models"
# Google's alias for its current Flash-Lite: fixed model names get retired, this one doesn't go away
FALLBACK_MODEL = "gemini-flash-lite-latest"

# Not text/vision chat models
_SKIP = ("tts", "image", "live", "embedding", "audio", "robotics", "computer-use", "aqa")

_retired: Dict[str, str] = {}             # model -> the model used instead (it answered 404)
_thinking: Dict[str, Optional[dict]] = {}  # model -> the thinking setting it accepted (None: none at all)


def headers(key: str) -> dict:
    """The key goes in a header: in the URL, request errors would quote it into logs and messages."""
    return {"Content-Type": "application/json", "x-goog-api-key": key}


def least_thinking(model: str) -> dict:
    """The setting for (almost) no thinking: 2.x models take a budget, newer ones a level."""
    return {"thinkingBudget": 0} if model.startswith("gemini-2") else {"thinkingLevel": "minimal"}


async def list_models(key: str) -> List[str]:
    """Gemini models the key can call generateContent on (no TTS, image, embedding... models), sorted.
    Empty if the key is missing or the request fails."""
    if not key:
        return []
    try:
        resp = await fetch("GET", API_URL, params={"pageSize": 200}, headers=headers(key))
    except NetworkError as e:
        logger.warning(f"Listing Gemini models failed: {e}")
        return []
    if resp.status_code != 200:
        logger.warning(f"Listing Gemini models failed: HTTP {resp.status_code}")
        return []
    names = [m.get("name", "").replace("models/", "") for m in resp.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    return sorted(n for n in names if n.startswith("gemini") and not any(s in n for s in _SKIP))


async def generate(key: str, model: str, payload: dict, timeout: float, thinking: bool = True) -> Tuple[Response, str]:
    """POST generateContent; returns (the last response, the model that answered).

    thinking=True asks for the least thinking the model allows (faster, cheaper; translation doesn't need it).
    Retries: a retired model (404) once with FALLBACK_MODEL; a 400 that isn't about the key with the least thinking
    level, then with no thinking setting (some models answer a setting they don't take with only "invalid argument")."""
    model = _retired.get(model, model)
    config = payload.setdefault("generationConfig", {})

    async def attempt(m: str, think: Optional[dict]) -> Response:
        if think is None:
            config.pop("thinkingConfig", None)
        else:
            config["thinkingConfig"] = think
        return await fetch("POST", f"{API_URL}/{m}:generateContent", json=payload, headers=headers(key),
                           timeout=timeout)

    def first_thinking(m: str) -> Optional[dict]:
        if not thinking:
            return None
        return _thinking[m] if m in _thinking else least_thinking(m)

    think = first_thinking(model)
    resp = await attempt(model, think)
    if resp.status_code == 404 and model != FALLBACK_MODEL:
        logger.warning(f"Gemini model {model} is not available (404); using {FALLBACK_MODEL} from now on")
        _retired[model] = FALLBACK_MODEL
        model = FALLBACK_MODEL
        think = first_thinking(model)
        resp = await attempt(model, think)
    ladder = [t for t in ({"thinkingLevel": "minimal"}, None) if t != think]
    for retry in ladder:
        if resp.status_code != 400 or "api key" in resp.text.lower() or think is None:
            break
        logger.info(f"{model} rejects thinkingConfig {think}; retrying with {retry}")
        think = retry
        resp = await attempt(model, think)
    if resp.status_code == 200 and thinking:
        _thinking[model] = think
    return resp, model
