# providers/free_translate.py
# Free translation using direct HTTP requests to Google Translate

import asyncio
import logging
import time
from typing import List, Optional

import requests

from .base import TranslationProvider, ProviderType, NetworkError, chunk_indices
from .bing_translate import BingTranslator

# one session per module: connections are kept alive between requests (a new TLS handshake per
# request doubled the time of short requests, e.g. 561 -> 258 ms to translate.googleapis.com)
_http = requests.Session()

GOOGLE_PAUSE_SECONDS = 15 * 60  # after a 429/403 from Google, use Bing for this long
GOOGLE_BATCH_CHARS = 4500       # texts per POST, one per line

logger = logging.getLogger(__name__)


class FreeTranslateProvider(TranslationProvider):
    """Translation provider using free Google Translate (unofficial API)."""

    # Language code mapping
    LANGUAGE_MAP = {
        'auto': 'auto',
        'en': 'en',
        'ja': 'ja',
        'zh-CN': 'zh-CN',
        'zh-TW': 'zh-TW',
        'ko': 'ko',
        'de': 'de',
        'fr': 'fr',
        'es': 'es',
        'it': 'it',
        'pt': 'pt',
        'ru': 'ru',
        'ar': 'ar',
        'el': 'el',
        'fi': 'fi',
        'nl': 'nl',
        'no': 'no',
        'pl': 'pl',
        'tr': 'tr',
        'uk': 'uk',
        'hi': 'hi',
        'th': 'th',
        'vi': 'vi',
        'id': 'id',
        'ro': 'ro',
        'bg': 'bg',
        'hr': 'hr',
        'cs': 'cs',
        'hu': 'hu',
        'sv': 'sv',
        'da': 'da',
    }

    SUPPORTED_LANGUAGES = list(LANGUAGE_MAP.keys())

    # Free Google Translate endpoint (unofficial)
    TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"

    def __init__(self):
        """Initialize the free translation provider."""
        self._google_paused_until = 0.0
        self._bing = BingTranslator()
        logger.debug("FreeTranslateProvider initialized")

    def _pause_google(self, status):
        self._google_paused_until = time.time() + GOOGLE_PAUSE_SECONDS
        logger.warning(f"Google Translate rate-limited ({status}); using Bing for {GOOGLE_PAUSE_SECONDS // 60} min")

    def _google_batch(self, texts: List[str], src: str, tgt: str) -> List[Optional[str]]:
        """All texts in as few POSTs as possible, one text per line; None where it failed (Bing fills those in)."""
        results: List[Optional[str]] = [None] * len(texts)
        chunks = chunk_indices(texts, GOOGLE_BATCH_CHARS, sep_chars=1)  # one text per line
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        for chunk in chunks:
            if time.time() < self._google_paused_until:
                break
            lines = [" ".join(texts[i].split()) for i in chunk]
            try:
                resp = _http.post(self.TRANSLATE_URL, params={'client': 'gtx', 'sl': src, 'tl': tgt, 'dt': 't'},
                                     data={'q': "\n".join(lines)}, headers=headers, timeout=10.0)
            except requests.exceptions.ConnectionError as e:
                raise NetworkError("No internet connection") from e
            except requests.exceptions.Timeout as e:
                raise NetworkError("Connection timed out") from e
            if resp.status_code in (403, 429):
                self._pause_google(resp.status_code)
                break
            if resp.status_code != 200:
                logger.warning(f"Translation request failed: {resp.status_code}")
                continue
            try:
                out = "".join((seg[0] or "") for seg in resp.json()[0] if seg).split("\n")
            except (ValueError, TypeError, IndexError):
                continue
            if len(out) == len(chunk):
                for i, t in zip(chunk, out):
                    results[i] = t.strip()
            else:
                logger.debug(f"Google returned {len(out)} lines for {len(chunk)}; Bing translates this chunk")
        for i, t in enumerate(texts):
            if not t or not t.strip():
                results[i] = t
        return results

    @property
    def name(self) -> str:
        return "Free Google Translate"

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.FREE_GOOGLE

    def _map_language(self, language: str) -> str:
        """Map our language codes to Google Translate codes."""
        return self.LANGUAGE_MAP.get(language, language)

    def is_available(self, source_lang: str, target_lang: str) -> bool:
        """Check if translation is available for the language pair."""
        return (
            source_lang in self.SUPPORTED_LANGUAGES or source_lang == 'auto'
        ) and target_lang in self.SUPPORTED_LANGUAGES

    def get_supported_languages(self) -> List[str]:
        """Return list of supported language codes."""
        return self.SUPPORTED_LANGUAGES.copy()

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        """
        Translate text from source to target language.

        Args:
            text: Text to translate
            source_lang: Source language code (or "auto" for detection)
            target_lang: Target language code

        Returns:
            Translated text
        """
        if not text or not text.strip():
            return text

        src = self._map_language(source_lang)
        tgt = self._map_language(target_lang)

        logger.debug(f"Translating: {src} -> {tgt}, text length: {len(text)}")

        # Run translation in thread pool to not block event loop
        result = (await asyncio.to_thread(self._translate_lines, [text], src, tgt))[0]

        return result if result is not None else text

    def _translate_lines(self, texts: List[str], src: str, tgt: str) -> List[Optional[str]]:
        """Google first (one request per batch), Bing for whatever Google didn't translate or while it is paused."""
        results: List[Optional[str]] = [None] * len(texts)
        if time.time() >= self._google_paused_until:
            results = self._google_batch(texts, src, tgt)
        missing = [i for i, r in enumerate(results) if r is None and texts[i] and texts[i].strip()]
        if missing:
            for i, t in zip(missing, self._bing.translate_lines([texts[i] for i in missing], src, tgt)):
                results[i] = t
        return results

    async def translate_batch(self, texts: List[str], source_lang: str, target_lang: str) -> List[str]:
        """
        Translate multiple texts: one Google request per batch (one text per line), with Microsoft Bing as the
        fallback while Google rate-limits. Failed items stay None so they aren't cached as real results.
        """
        if not texts:
            return texts

        src = self._map_language(source_lang)
        tgt = self._map_language(target_lang)
        logger.debug(f"Batch translating {len(texts)} texts: {src} -> {tgt}")
        results = await asyncio.to_thread(self._translate_lines, list(texts), src, tgt)
        logger.debug(f"Batch translation complete: {len(results)} results")
        return results

    async def test_network(self) -> tuple:
        def _probe():
            params = {
                "client": "gtx",
                "sl": "en",
                "tl": "en",
                "dt": "t",
                "q": "ok",
            }
            try:
                resp = _http.get(self.TRANSLATE_URL, params=params, timeout=4)
            except (requests.ConnectionError, requests.Timeout):
                return False, "Network unreachable"
            except Exception as e:
                return False, f"Probe failed: {type(e).__name__}"
            code = resp.status_code
            if code == 200:
                return True, ""
            if code in (403, 429):
                return False, "Rate limited"
            return False, f"Service error ({code})"

        return await asyncio.to_thread(_probe)
