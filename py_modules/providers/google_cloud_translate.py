"""Google Cloud Translation API (needs the user's API key)."""

import logging
from typing import List

from .base import ApiKeyError, TranslationError, TranslationProvider, api_error, error_message, fetch, probe

logger = logging.getLogger(__name__)


class GoogleCloudTranslateProvider(TranslationProvider):
    def __init__(self, api_key: str = ""):
        self._api_key = api_key
        self._endpoint = "https://translation.googleapis.com/language/translate/v2"
        logger.debug("GoogleCloudTranslateProvider initialized")

    def set_api_key(self, api_key: str) -> None:
        self._api_key = api_key

    @property
    def name(self) -> str:
        return "Google Cloud Translation"

    def is_available(self, source_lang: str, target_lang: str) -> bool:
        return bool(self._api_key)

    async def translate_batch(self, texts: List[str], source_lang: str, target_lang: str) -> List[str]:
        if not self._api_key:
            raise ApiKeyError("API key required for Translation")

        if not texts:
            return texts

        request_data = {"q": texts, "target": target_lang, "format": "text"}
        if source_lang and source_lang != "auto":
            request_data["source"] = source_lang
        response = await fetch("POST", self._endpoint, json=request_data, headers={"x-goog-api-key": self._api_key})
        if response.status_code != 200:
            raise api_error(response, self.name)
        try:
            return [t["translatedText"] for t in response.json()["data"]["translations"]]
        except (ValueError, KeyError, TypeError) as e:
            logger.error(f"Unexpected response from the Translation API: {response.text[:500]}")
            raise TranslationError("Google Cloud Translation gave an unreadable answer (details in the plugin log)") from e

    async def test_network(self) -> tuple:
        if not self._api_key:
            return False, "API key required"
        resp, error = await probe("GET", f"{self._endpoint}/languages", headers={"x-goog-api-key": self._api_key})
        if resp is None:
            return False, error
        if resp.status_code == 200:
            return True, ""
        return False, error_message(resp)
