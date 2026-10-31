# providers/free_translate.py
# Free translation using direct HTTP requests to Google Translate

import logging
import time
from typing import List, Optional

from .base import TranslationProvider, chunk_indices, fetch, probe
from .bing_translate import BingTranslator

GOOGLE_PAUSE_SECONDS = 15 * 60  # after a 429/403 from Google, use Bing for this long
GOOGLE_BATCH_CHARS = 4500       # texts per POST, one per line

logger = logging.getLogger(__name__)


class FreeTranslateProvider(TranslationProvider):
    """Translation provider using free Google Translate (unofficial API)."""

    # The plugin's language codes are Google Translate's (and Bing's, mapped in bing_translate.py)
    SUPPORTED_LANGUAGES = [
        'en', 'ja', 'zh-CN', 'zh-TW', 'ko', 'de', 'fr', 'es', 'it', 'pt', 'ru', 'ar', 'el', 'fi', 'nl', 'no', 'pl',
        'tr', 'uk', 'hi', 'th', 'vi', 'id', 'ro', 'bg', 'hr', 'cs', 'hu', 'sv', 'da',
    ]

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

    async def _google_batch(self, texts: List[str], src: str, tgt: str) -> List[Optional[str]]:
        """All texts in as few POSTs as possible, one text per line; None where it failed (Bing fills those in)."""
        results: List[Optional[str]] = [None] * len(texts)
        chunks = chunk_indices(texts, GOOGLE_BATCH_CHARS, sep_chars=1)  # one text per line
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        for chunk in chunks:
            if time.time() < self._google_paused_until:
                break
            lines = [" ".join(texts[i].split()) for i in chunk]
            resp = await fetch("POST", self.TRANSLATE_URL, params={'client': 'gtx', 'sl': src, 'tl': tgt, 'dt': 't'},
                               data={'q': "\n".join(lines)}, headers=headers)
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

    def is_available(self, source_lang: str, target_lang: str) -> bool:
        """Check if translation is available for the language pair."""
        return (
            source_lang in self.SUPPORTED_LANGUAGES or source_lang == 'auto'
        ) and target_lang in self.SUPPORTED_LANGUAGES

    async def _translate_lines(self, texts: List[str], src: str, tgt: str) -> List[Optional[str]]:
        """Google first (one request per batch), Bing for whatever Google didn't translate or while it is paused."""
        results: List[Optional[str]] = [None] * len(texts)
        if time.time() >= self._google_paused_until:
            results = await self._google_batch(texts, src, tgt)
        missing = [i for i, r in enumerate(results) if r is None and texts[i] and texts[i].strip()]
        if missing:
            for i, t in zip(missing, await self._bing.translate_lines([texts[i] for i in missing], src, tgt)):
                results[i] = t
        return results

    async def translate_batch(self, texts: List[str], source_lang: str, target_lang: str) -> List[str]:
        """
        Translate multiple texts: one Google request per batch (one text per line), with Microsoft Bing as the
        fallback while Google rate-limits. Failed items stay None so they aren't cached as real results.
        """
        if not texts:
            return texts

        logger.debug(f"Batch translating {len(texts)} texts: {source_lang} -> {target_lang}")
        results = await self._translate_lines(list(texts), source_lang, target_lang)
        logger.debug(f"Batch translation complete: {len(results)} results")
        return results

    async def test_network(self) -> tuple:
        resp, error = await probe("GET", self.TRANSLATE_URL,
                                  params={"client": "gtx", "sl": "en", "tl": "en", "dt": "t", "q": "ok"})
        if resp is None:
            return False, error
        if resp.status_code == 200:
            return True, ""
        if resp.status_code in (403, 429):
            return False, "Rate limited"
        return False, f"Service error ({resp.status_code})"
