# providers/bing_translate.py
# Microsoft's free web translator (bing.com/translator), the fallback of the free Google provider when Google rate-limits
# (HTTP 429/403). Like the web page: read IG/IID and the anti-abuse key/token from bing.com/translator (the token lives
# an hour), then POST to /ttranslatev3. Several texts go in one request, one per line; Bing keeps the line breaks.

import logging
import re
import time
from typing import List, Optional

from .base import NetworkError, chunk_indices, fetch

logger = logging.getLogger(__name__)

PAGE_URL = "https://www.bing.com/translator"
TRANSLATE_URL = "https://www.bing.com/ttranslatev3"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/130.0.0.0 Safari/537.36"}
MAX_CHARS = 1000  # the web page's limit per request

# plugin language codes Bing spells differently
_LANG = {"auto": "auto-detect", "zh-CN": "zh-Hans", "zh-TW": "zh-Hant", "no": "nb", "tl": "fil", "iw": "he"}


class RateLimited(Exception):
    pass


class BingTranslator:
    """The page's cookies stay in the shared session's cookie jar, as a browser keeps them."""

    def __init__(self):
        self._params = None      # (IG, IID, key, token)
        self._expires = 0.0

    async def _refresh(self):
        page = (await fetch("GET", PAGE_URL, headers=HEADERS)).text
        ig = re.search(r'IG:"([A-F0-9]+)"', page)
        iid = re.search(r'data-iid="([^"]+)"', page)
        ab = re.search(r'params_AbusePreventionHelper\s*=\s*\[(\d+),"([^"]+)",(\d+)\]', page)
        if not (ig and ab):
            raise RuntimeError("Bing translator page changed: token not found")
        self._params = (ig.group(1), iid.group(1) if iid else "translator.5023", ab.group(1), ab.group(2))
        self._expires = time.time() + int(ab.group(3)) / 1000 - 120

    async def _request(self, text: str, src: str, tgt: str) -> str:
        if self._params is None or time.time() > self._expires:
            await self._refresh()
        ig, iid, key, token = self._params
        resp = await fetch(
            "POST", TRANSLATE_URL, params={"isVertical": "1", "IG": ig, "IID": iid}, headers=HEADERS,
            data={"fromLang": _LANG.get(src, src), "to": _LANG.get(tgt, tgt), "text": text, "token": token, "key": key},
        )
        if resp.status_code in (403, 429):
            raise RateLimited(resp.status_code)
        data = resp.json()
        if isinstance(data, dict):  # {"statusCode": 205, ...}: token stale or throttled
            self._params = None
            raise RateLimited(data.get("statusCode"))
        return data[0]["translations"][0]["text"]

    async def translate_lines(self, texts: List[str], src: str, tgt: str) -> List[Optional[str]]:
        """Translate texts with as few requests as possible; None for any text that failed."""
        results: List[Optional[str]] = [t if not t or not t.strip() else None for t in texts]
        for chunk in chunk_indices(texts, MAX_CHARS, sep_chars=1):
            lines = [" ".join(texts[i].split()) for i in chunk]  # one line per text
            try:
                out = (await self._request("\n".join(lines), src, tgt)).split("\n")
                if len(out) == len(chunk):
                    for i, t in zip(chunk, out):
                        results[i] = t.strip()
                else:  # Bing merged or split lines: translate this chunk one text at a time
                    for i, line in zip(chunk, lines):
                        results[i] = (await self._request(line, src, tgt)).strip()
            except NetworkError:
                raise
            except Exception as e:  # noqa: BLE001 - leave these None, the caller decides
                logger.warning(f"Bing translation failed: {e!r}")
        return results
