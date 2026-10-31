# providers/google_translate.py
# Google Cloud Translation provider

import logging
from typing import List

from .base import (TranslationProvider, NetworkError, ApiKeyError, RateLimitError, TranslationError,
                   classify_google_error, fetch, probe, raise_for_google_error)

logger = logging.getLogger(__name__)


class GoogleTranslateProvider(TranslationProvider):
    """Translation provider using Google Cloud Translation API."""

    SUPPORTED_LANGUAGES = [
        'auto', 'en', 'ja', 'zh-CN', 'zh-TW', 'ko', 'de', 'fr', 'es', 'it',
        'pt', 'ru', 'ar', 'nl', 'no', 'pl', 'tr', 'uk', 'hi', 'el', 'th', 'vi', 'fi', 'id', 'ro', 'bg', 'hr',
        'cs', 'hu', 'sv', 'da'
    ]

    def __init__(self, api_key: str = ""):
        """Initialize the Google Translate provider."""
        self._api_key = api_key
        self._endpoint = "https://translation.googleapis.com/language/translate/v2"
        logger.debug("GoogleTranslateProvider initialized")

    def set_api_key(self, api_key: str) -> None:
        """Update the API key."""
        self._api_key = api_key

    @property
    def name(self) -> str:
        return "Google Cloud Translation"

    def is_available(self, source_lang: str, target_lang: str) -> bool:
        """Check if translation is available for the language pair."""
        if not self._api_key:
            return False
        return (
            (source_lang in self.SUPPORTED_LANGUAGES or source_lang == 'auto') and
            target_lang in self.SUPPORTED_LANGUAGES
        )

    async def translate_batch(self, texts: List[str], source_lang: str, target_lang: str) -> List[str]:
        """
        Translate multiple texts using Google Cloud Translation API.

        Args:
            texts: List of texts to translate
            source_lang: Source language code
            target_lang: Target language code

        Returns:
            List of translated texts
        """
        if not self._api_key:
            raise ApiKeyError("API key required for Translation")

        if not texts:
            return texts

        request_data = {"q": texts, "target": target_lang, "format": "text"}
        if source_lang and source_lang != "auto":
            request_data["source"] = source_lang
        try:
            logger.debug(f"Translating {len(texts)} texts: {source_lang} -> {target_lang}")
            response = await fetch("POST", self._endpoint, json=request_data, headers={"x-goog-api-key": self._api_key})
            if response.status_code != 200:
                raise_for_google_error(response)
                raise TranslationError(f"Google Cloud Translation: API error ({response.status_code})")

            result = response.json()

            if 'data' in result and 'translations' in result['data']:
                translations = result['data']['translations']
                translated_texts = []
                for i, translation in enumerate(translations):
                    translated_text = translation.get('translatedText', texts[i] if i < len(texts) else '')
                    translated_texts.append(translated_text)
                logger.debug(f"Successfully translated {len(translated_texts)} texts")
                return translated_texts
            else:
                logger.error(f"Unexpected response from the Translation API: {response.text[:500]}")
                raise TranslationError("Google Cloud Translation gave an unreadable answer (details in the plugin log)")

        except (ApiKeyError, RateLimitError, NetworkError, TranslationError):
            raise
        except Exception as e:
            logger.exception("Batch translation error")
            raise TranslationError("Google Cloud Translation failed (details in the plugin log)") from e

    async def test_network(self) -> tuple:
        if not self._api_key:
            return False, "API key required"
        resp, error = await probe("GET", f"{self._endpoint}/languages", headers={"x-goog-api-key": self._api_key})
        if resp is None:
            return False, error
        if resp.status_code == 200:
            return True, ""
        return False, classify_google_error(resp.status_code, resp.text)
