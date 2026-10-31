# providers/gemini_vision.py
# Gemini Vision provider -- combined OCR + translation in a single API call

import base64
import io
import json
import logging
import re
from typing import List, Optional

from PIL import Image

from . import gemini_api
from .base import (
    OCRProvider,
    ProviderType,
    TextRegion,
    ApiKeyError,
    classify_google_error,
    probe,
    raise_for_api_error,
)

logger = logging.getLogger(__name__)

# gemini-2.5-flash (upstream's default) answers 404 "no longer available to new users" since 2026. On a 1920x1200 game
# frame (2026-10-30): gemini-3.5-flash 12 s, gemini-flash-lite-latest 6.5 s, gemini-flash-latest 55-77 s (too slow).
DEFAULT_MODEL = "gemini-3.5-flash"  # a retired model falls back to gemini_api.FALLBACK_MODEL
REQUEST_TIMEOUT = 30

# Gemini's reply: each line of text on the screen, its translation and its box (y0, x0, y1, x1 in 0-1000)
REGIONS_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "text": {"type": "STRING"},
            "translated_text": {"type": "STRING"},
            "box_2d": {"type": "ARRAY", "items": {"type": "NUMBER"}},
        },
        "required": ["text", "translated_text", "box_2d"],
    },
}

# Language code to natural name for the prompt
LANG_NAMES = {
    "auto": "auto-detect",
    "en": "English", "ja": "Japanese", "ko": "Korean",
    "zh-CN": "Simplified Chinese", "zh-TW": "Traditional Chinese",
    "de": "German", "fr": "French", "es": "Spanish",
    "it": "Italian", "pt": "Portuguese", "nl": "Dutch",
    "pl": "Polish", "tr": "Turkish", "ro": "Romanian",
    "vi": "Vietnamese", "fi": "Finnish", "ru": "Russian",
    "uk": "Ukrainian", "el": "Greek", "th": "Thai",
    "bg": "Bulgarian", "ar": "Arabic", "hi": "Hindi",
    "id": "Indonesian", "ms": "Malay", "sv": "Swedish",
    "da": "Danish", "no": "Norwegian", "cs": "Czech",
    "hu": "Hungarian", "he": "Hebrew", "hr": "Croatian",
}


_SEPARATOR = re.compile(r'\s*,?\s*')


def _as_regions(value) -> Optional[list]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and isinstance(value.get("regions"), list):
        return value["regions"]
    return None


def _parse_json_response(text: str) -> Optional[list]:
    """The regions array from Gemini's reply text: the JSON itself, inside a markdown fence, embedded in prose, or a
    reply cut off mid-array (then the complete region objects before the cut). json.JSONDecoder.raw_decode does the
    scanning, so brackets inside the region texts don't confuse it."""
    cleaned = re.sub(r'<think>.*?</think>', '', text.strip(), flags=re.DOTALL)
    cleaned = re.sub(r'<reasoning>.*?</reasoning>', '', cleaned, flags=re.DOTALL).strip()
    fence = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', cleaned, re.DOTALL)
    candidates = [cleaned] + ([fence.group(1).strip()] if fence else [])
    for candidate in candidates:
        try:
            regions = _as_regions(json.loads(candidate))
        except json.JSONDecodeError:
            continue
        if regions is not None:
            return regions

    decoder = json.JSONDecoder()
    # JSON embedded in other text: decode from the first bracket
    starts = [i for i in (cleaned.find('['), cleaned.find('{')) if i != -1]
    if starts:
        try:
            regions = _as_regions(decoder.raw_decode(cleaned, min(starts))[0])
            if regions is not None:
                return regions
        except json.JSONDecodeError:
            pass

    # A reply cut off mid-array: keep each complete top-level object of the array
    array = cleaned.find('[')
    if array != -1:
        regions, pos = [], array + 1
        while True:
            pos = _SEPARATOR.match(cleaned, pos).end()
            if pos >= len(cleaned) or cleaned[pos] != '{':
                break
            try:
                obj, pos = decoder.raw_decode(cleaned, pos)
            except json.JSONDecodeError:
                break  # the object the reply was cut in
            regions.append(obj)
        if regions:
            logger.warning(f"Recovered {len(regions)} regions from truncated response")
            return regions

    logger.warning("Failed to parse JSON from Gemini response")
    logger.debug(f"Response text: {cleaned[:500]}")
    return None


def _validate_region(region: dict) -> bool:
    """Check that a region dict has the required fields."""
    if not isinstance(region, dict):
        return False
    if "text" not in region or "box_2d" not in region:
        return False
    box = region["box_2d"]
    if not isinstance(box, list) or len(box) != 4:
        return False
    return all(isinstance(v, (int, float)) for v in box)


class GeminiVisionProvider(OCRProvider):
    """
    Uses Gemini Vision to detect and translate text in screenshots
    in a single API call. Returns TextRegion objects with translated_text set.
    """

    def __init__(self, api_key: str = "", model: str = DEFAULT_MODEL):
        self._api_key = api_key
        self._model = model
        self._target_language = "en"

    def set_api_key(self, api_key: str) -> None:
        self._api_key = api_key

    def set_target_language(self, target_lang: str) -> None:
        self._target_language = target_lang

    @property
    def name(self) -> str:
        return "Gemini Vision"

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.GEMINI_VISION

    def is_available(self, language: str = "auto") -> bool:
        return bool(self._api_key)

    def get_supported_languages(self) -> List[str]:
        return list(LANG_NAMES.keys())

    def _build_system_instruction(self) -> str:
        return (
            "You detect and translate text in game screenshots. "
            "For each text region, return its box_2d as [ymin, xmin, ymax, xmax] in normalized 0-1000 coordinates. "
            "Return a JSON array covering every readable text region in the image."
        )

    def _build_prompt(self, source_lang: str, target_lang: str) -> str:
        tgt_name = LANG_NAMES.get(target_lang, target_lang)

        source_hint = ""
        if source_lang and source_lang != "auto":
            src_name = LANG_NAMES.get(source_lang, source_lang)
            source_hint = f" The source language is {src_name}."

        prompt = (
            f"Detect the 2D bounding boxes of all visible text in this screenshot.\n"
            f"For each text region return: the original text, its translation to {tgt_name}, "
            f"and the box_2d coordinates.{source_hint}\n\n"
            f"Grouping rules:\n"
            f"- Merge text that shares the same font size, color, and belongs to the same visual block (e.g. a dialog box, tooltip, or paragraph).\n"
            f"- Keep text separate when it differs in font size, color, or visual style, even if spatially close.\n"
            f"- Each menu item, button label, stat value, or HUD element should be its own region.\n\n"
            f"If the text is already in {tgt_name}, set translated_text to the original text."
        )
        return prompt

    async def _call_api(self, image_data: bytes, prompt: str) -> str:
        payload = {
            "system_instruction": {"parts": [{"text": self._build_system_instruction()}]},
            "contents": [{
                "parts": [
                    {"inline_data": {"mime_type": "image/png", "data": base64.b64encode(image_data).decode('utf-8')}},
                    {"text": prompt},
                ]
            }],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 32768,
                "responseMimeType": "application/json",
                "responseSchema": REGIONS_SCHEMA,
            },
        }
        # retired model -> current alias, thinking setting the model rejects -> less (gemini_api.generate)
        response, _ = await gemini_api.generate(self._api_key, self._model, payload, REQUEST_TIMEOUT)
        raise_for_api_error(response, "Gemini Vision")
        return gemini_api.reply_text(response)

    async def recognize(self, image_data: bytes, language: str = "auto") -> List[TextRegion]:
        if not self._api_key:
            raise ApiKeyError("Gemini API key not configured")

        img_width, img_height = Image.open(io.BytesIO(image_data)).size

        prompt = self._build_prompt(language, self._target_language)

        response_text = await self._call_api(image_data, prompt)

        regions_data = _parse_json_response(response_text)
        if regions_data is None:
            return []

        raw_region_count = len(regions_data)
        text_regions = []
        for region in regions_data:
            if not _validate_region(region):
                continue

            box = region["box_2d"]  # [y_min, x_min, y_max, x_max]
            y_min, x_min, y_max, x_max = box

            # Clamp to valid range before converting to pixel coords
            x_min = max(0, min(1000, x_min))
            y_min = max(0, min(1000, y_min))
            x_max = max(0, min(1000, x_max))
            y_max = max(0, min(1000, y_max))

            rect = {
                "left": int(x_min * img_width / 1000),
                "top": int(y_min * img_height / 1000),
                "right": int(x_max * img_width / 1000),
                "bottom": int(y_max * img_height / 1000),
            }

            text = region.get("text", "").strip()
            translated = region.get("translated_text", "").strip()
            if not text:
                continue

            text_regions.append(TextRegion(
                text=text,
                rect=rect,
                confidence=0.9,
                translated_text=translated if translated else text,
            ))

        logger.info(
            f"Gemini Vision: {len(text_regions)}/{raw_region_count} valid regions"
        )
        for i, r in enumerate(text_regions):
            logger.debug(f"  [{i}] '{r.text}' -> '{r.translated_text}' at {r.rect}")

        return text_regions

    async def list_available_models(self) -> List[str]:
        """Fetch available flash models from Gemini API."""
        if not self._api_key:
            return []
        # Flash models read images fast
        models = [m for m in await gemini_api.list_models(self._api_key) if "flash" in m]
        logger.info(f"Available Gemini models: {models}")
        return models

    async def test_network(self) -> tuple:
        if not self._api_key:
            return False, "API key required"
        resp, error = await probe("GET", gemini_api.API_URL, params={"pageSize": 1},
                                  headers=gemini_api.headers(self._api_key))
        if resp is None:
            return False, error
        if resp.status_code == 200:
            return True, ""
        return False, classify_google_error(resp.status_code, resp.text)
