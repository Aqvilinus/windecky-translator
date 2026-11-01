"""Gemini Vision: OCR and translation of a screenshot in a single API call."""

import asyncio
import base64
import io
import json
import logging
import re
from typing import List


from . import gemini_client
from .base import (
    OCRProvider,
    TextRegion,
    ApiKeyError,
    api_error,
    error_message,
    probe,
    to_jpeg,
)

logger = logging.getLogger(__name__)

# gemini-2.5-flash (upstream's default) answers 404 "no longer available to new users" since 2026. On a 1920x1200 game
# frame (2026-10-30): gemini-3.5-flash 12 s, gemini-flash-lite-latest 6.5 s, gemini-flash-latest 55-77 s (too slow).
DEFAULT_MODEL = "gemini-3.5-flash"  # a retired model falls back to gemini_client.FALLBACK_MODEL
REQUEST_TIMEOUT_SECONDS = 30

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

# for the prompts
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


def _parse_regions(text: str) -> list:
    """The regions of Gemini's reply, a JSON array by REGIONS_SCHEMA. A reply cut off at the token limit gives the
    complete region objects before the cut (json.JSONDecoder.raw_decode reads each, so brackets inside the region
    texts don't confuse it)."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    regions, pos = [], text.find('[') + 1
    while pos:
        pos = _SEPARATOR.match(text, pos).end()
        if pos >= len(text) or text[pos] != '{':
            break
        try:
            obj, pos = decoder.raw_decode(text, pos)
        except json.JSONDecodeError:
            break  # the object the reply was cut in
        regions.append(obj)
    logger.warning(f"Gemini's reply was cut off: {len(regions)} complete regions kept")
    logger.debug(f"Response text: {text[:500]}")
    return regions


class GeminiVisionProvider(OCRProvider):
    """Its TextRegions come with translated_text set."""

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

    def is_available(self) -> bool:
        return bool(self._api_key)

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
                    {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(image_data).decode('utf-8')}},
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
        # retired model -> current alias, thinking setting the model rejects -> less (gemini_client.generate)
        response = await gemini_client.generate(self._api_key, self._model, payload, REQUEST_TIMEOUT_SECONDS)
        if response.status_code != 200:
            raise api_error(response, "Gemini Vision")
        return gemini_client.reply_text(response)

    async def recognize(self, image_data: bytes, language: str = "auto") -> List[TextRegion]:
        if not self._api_key:
            raise ApiKeyError("Gemini API key not configured")

        from PIL import Image  # Pillow is imported where it's used (see main.py STARTUP_ERRORS)
        img_width, img_height = Image.open(io.BytesIO(image_data)).size

        prompt = self._build_prompt(language, self._target_language)

        response_text = await self._call_api(await asyncio.to_thread(to_jpeg, image_data), prompt)

        regions_data = _parse_regions(response_text)
        text_regions = []
        for region in regions_data:
            box = region["box_2d"]
            if len(box) != 4:  # the schema can't say how many numbers
                continue
            y_min, x_min, y_max, x_max = box

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

            text = region["text"].strip()
            translated = region["translated_text"].strip()
            if not text:
                continue

            text_regions.append(TextRegion(
                text=text,
                rect=rect,
                translated_text=translated if translated else text,
            ))

        logger.info(
            f"Gemini Vision: {len(text_regions)}/{len(regions_data)} valid regions"
        )
        for i, r in enumerate(text_regions):
            logger.debug(f"  [{i}] '{r.text}' -> '{r.translated_text}' at {r.rect}")

        return text_regions

    async def list_available_models(self) -> List[str]:
        if not self._api_key:
            return []
        # Flash models read images fast
        models = [m for m in await gemini_client.list_models(self._api_key) if "flash" in m]
        logger.info(f"Available Gemini models: {models}")
        return models

    async def test_network(self) -> tuple:
        if not self._api_key:
            return False, "API key required"
        resp, error = await probe("GET", gemini_client.API_URL, params={"pageSize": 1},
                                  headers=gemini_client.headers(self._api_key))
        if resp is None:
            return False, error
        if resp.status_code == 200:
            return True, ""
        return False, error_message(resp)
