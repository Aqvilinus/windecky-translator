"""Google Cloud Vision OCR (needs the user's API key)."""

import asyncio
import base64
import logging
from typing import List, Optional

from .base import ApiKeyError, OCRError, OCRProvider, TextRegion, api_error, error_message, fetch, probe, to_jpeg

logger = logging.getLogger(__name__)


class GoogleCloudVisionProvider(OCRProvider):
    def __init__(self, api_key: str = ""):
        self._api_key = api_key
        self._endpoint = "https://vision.googleapis.com/v1/images:annotate"
        logger.debug("GoogleCloudVisionProvider initialized")

    def set_api_key(self, api_key: str) -> None:
        self._api_key = api_key

    @property
    def name(self) -> str:
        return "Google Cloud Vision"

    def is_available(self) -> bool:
        return bool(self._api_key)

    async def recognize(self, image_data: bytes, language: str = "auto") -> List[TextRegion]:
        """language is unused: Google Vision detects it."""
        request_data = {
            "requests": [{
                "image": {"content": base64.b64encode(await asyncio.to_thread(to_jpeg, image_data)).decode('utf-8')},
                "features": [{"type": "DOCUMENT_TEXT_DETECTION", "maxResults": 50}],
            }]
        }
        response = await fetch("POST", self._endpoint, json=request_data, headers={"x-goog-api-key": self._api_key})
        if response.status_code != 200:
            raise api_error(response, "Google Cloud Vision")
        try:
            result = response.json()["responses"][0]
        except (ValueError, KeyError, IndexError) as e:
            raise OCRError("Google Cloud Vision gave an unreadable answer (details in the plugin log)") from e
        if "error" in result:  # a request-level error comes with HTTP 200
            raise OCRError(f"Google Cloud Vision: {result['error'].get('message', result['error'])}")
        pages = result.get("fullTextAnnotation", {}).get("pages", [])
        return [region for page in pages[:1] for block in page.get("blocks", [])
                for paragraph in block.get("paragraphs", []) if (region := _paragraph_region(paragraph))]

    async def test_network(self) -> tuple:
        if not self._api_key:
            return False, "API key required"
        resp, error = await probe("POST", self._endpoint, json={"requests": []},
                                  headers={"x-goog-api-key": self._api_key})
        if resp is None:
            return False, error
        if resp.status_code == 200:
            return True, ""
        if resp.status_code == 400 and not isinstance(api_error(resp, ""), ApiKeyError):
            return True, ""  # the empty request refused, the key accepted
        return False, error_message(resp)


def _paragraph_region(paragraph: dict) -> Optional[TextRegion]:
    text = " ".join("".join(s.get("text", "") for s in w.get("symbols", [])) for w in paragraph.get("words", []))
    text = text.strip()
    if not text:
        return None
    vertices = paragraph["boundingBox"]["vertices"]
    xs = [v.get("x", 0) for v in vertices]  # a zero coordinate is left out of Google's JSON
    ys = [v.get("y", 0) for v in vertices]
    return TextRegion(text=text, rect={"left": min(xs), "top": min(ys), "right": max(xs), "bottom": max(ys)},
                      confidence=paragraph.get("confidence"))
