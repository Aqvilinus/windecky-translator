# providers/windows_ocr.py
# OCR with Windows' own engine (Windows.Media.Ocr), for Decky Loader on Windows.
# On-device, no download: Windows ships the engine, and each language needs its OCR language pack
# (Settings > Time & language > Language, or `Add-WindowsCapability -Online -Name Language.OCR~~~ja-JP~0.0.1.0`).
# Returns one region per text line; the frontend groups lines into paragraphs (TextRecognizer.tsx).

import asyncio
import io
import logging
import sys
from typing import List, Optional

from .base import OCRProvider, ProviderType, TextRegion

logger = logging.getLogger(__name__)

# Chinese: Windows normalises tags with the script ("zh-CN" pack -> "zh-Hans-CN"); the plugin codes are by script
_ZH_SIMPLIFIED = ("zh-hans", "zh-cn", "zh-sg")
_ZH_TRADITIONAL = ("zh-hant", "zh-tw", "zh-hk", "zh-mo")


def plugin_code(tag: str) -> str:
    """A Windows language tag as a plugin language code: "en-US" -> "en", "zh-Hans-CN" -> "zh-CN"."""
    t = (tag or "").lower()
    if t.startswith(_ZH_SIMPLIFIED) or t == "zh":
        return "zh-CN"
    if t.startswith(_ZH_TRADITIONAL):
        return "zh-TW"
    return t.split("-")[0]


def _winrt():
    from winrt.windows.globalization import Language
    from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter
    return Language, BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap, OcrEngine, DataWriter


class WindowsOCRProvider(OCRProvider):
    def __init__(self):
        self._engines = {}

    @property
    def name(self) -> str:
        return "Windows OCR"

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.WINDOWS_OCR

    @staticmethod
    def installed_languages() -> List[str]:
        try:
            _, _, _, _, OcrEngine, _ = _winrt()
            return [lang.language_tag for lang in OcrEngine.available_recognizer_languages]
        except Exception as e:
            logger.warning(f"Windows OCR unavailable: {e}")
            return []

    def _engine(self, language: str):
        Language, _, _, _, OcrEngine, _ = _winrt()
        want = "" if not language or language == "auto" else plugin_code(language)
        if want in self._engines:
            return self._engines[want]
        engine: Optional[object] = None
        if want:
            # the installed pack for the language ("en" -> "en-US"; "zh-TW" -> "zh-Hant-TW", not a Simplified pack)
            for lang in OcrEngine.available_recognizer_languages:
                if plugin_code(lang.language_tag) == want:
                    engine = OcrEngine.try_create_from_language(Language(lang.language_tag))
                    break
        if engine is None:
            engine = OcrEngine.try_create_from_user_profile_languages()
        self._engines[want] = engine
        return engine

    def is_available(self, language: str = "auto") -> bool:
        return sys.platform == "win32" and bool(self.installed_languages())

    def get_supported_languages(self) -> List[str]:
        """The installed OCR packs as plugin codes ("en-US" -> "en", "zh-Hans-CN" -> "zh-CN")."""
        return sorted({plugin_code(t) for t in self.installed_languages()})

    async def recognize(self, image_data: bytes, language: str = "auto") -> List[TextRegion]:
        from PIL import Image
        _, BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap, OcrEngine, DataWriter = _winrt()

        engine = self._engine(language)
        if engine is None:
            raise RuntimeError(f"No Windows OCR language pack for '{language}'. Installed: {self.installed_languages()}")

        limit = OcrEngine.max_image_dimension

        def prepare():  # decoding a full-screen PNG takes tens of ms: off the event loop
            img = Image.open(io.BytesIO(image_data)).convert("RGBA")
            scale = 1.0
            if max(img.size) > limit:
                scale = limit / max(img.size)
                img = img.resize((int(img.width * scale), int(img.height * scale)))
            return img.tobytes("raw", "BGRA"), img.width, img.height, scale

        bgra, width, height, scale = await asyncio.to_thread(prepare)
        writer = DataWriter()
        writer.write_bytes(bgra)
        bitmap = SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(), BitmapPixelFormat.BGRA8,
                                                        width, height, BitmapAlphaMode.PREMULTIPLIED)
        result = await engine.recognize_async(bitmap)

        regions: List[TextRegion] = []
        for line in result.lines:
            words = list(line.words)
            if not words:
                continue
            left = min(w.bounding_rect.x for w in words)
            top = min(w.bounding_rect.y for w in words)
            right = max(w.bounding_rect.x + w.bounding_rect.width for w in words)
            bottom = max(w.bounding_rect.y + w.bounding_rect.height for w in words)
            regions.append(TextRegion(
                text=line.text,
                rect={"left": int(left / scale), "top": int(top / scale),
                      "right": int(right / scale), "bottom": int(bottom / scale)},
                confidence=1.0,  # Windows OCR reports no confidence
            ))
        logger.info(f"Windows OCR ({engine.recognizer_language.language_tag}): {len(regions)} lines")
        return regions
