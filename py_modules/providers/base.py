# providers/base.py
# Abstract base classes for OCR and Translation providers

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Optional
from enum import Enum


class NetworkError(Exception):
    """Raised when a network connection error occurs."""
    pass


class ApiKeyError(Exception):
    """Raised when the API key is invalid or missing."""
    pass


class RateLimitError(Exception):
    """Raised when API rate limit is exceeded."""
    pass


def classify_google_error(status_code: int, body: str) -> str:
    """Logging for a non-200 Google API response."""
    body = body or ""
    if 'API_KEY_INVALID' in body or 'API key not valid' in body:
        return "Invalid API key"
    if 'SERVICE_DISABLED' in body or 'has not been used' in body or 'it is disabled' in body:
        return "API not enabled in Cloud project"
    if 'BILLING_DISABLED' in body or 'billing' in body:
        return "Billing not enabled"
    if status_code == 401:
        return "Invalid API key"
    if status_code == 403:
        return "Access blocked (key restriction)"
    if status_code == 429:
        return "Rate limited"
    return f"API error ({status_code})"


class ProviderType(Enum):
    """Enum for available provider types."""
    GOOGLE = "google"           # Google Cloud (requires API key)
    OCR_SPACE = "ocrspace"      # OCR.space (free, no key needed)
    FREE_GOOGLE = "freegoogle"  # Free Google Translate via deep-translator
    RAPIDOCR = "rapidocr"       # Local RapidOCR via ONNX Runtime (no internet required)
    GEMINI_VISION = "gemini_vision"  # Gemini Vision (OCR + translation in one step)
    CT2 = "ct2"                 # CTranslate2 translation
    CHROME_SCREEN_AI = "chromescreenai"  # Chrome Screen AI
    WINDOWS_OCR = "windows_ocr"  # Windows.Media.Ocr (Windows only)
    LLM = "llm"                 # AI translation (Gemini / Groq / OpenAI-compatible), Google -> Bing fallback


@dataclass
class TextRegion:
    """Represents a detected text region from OCR."""
    text: str
    rect: Dict[str, int]  # left, top, right, bottom
    confidence: float = 0.0
    is_dialog: bool = False
    translated_text: Optional[str] = None  # Pre-translated text

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        d = {
            "text": self.text,
            "rect": self.rect,
            "confidence": self.confidence,
            "isDialog": self.is_dialog
        }
        if self.translated_text is not None:
            d["translatedText"] = self.translated_text
        return d


class OCRProvider(ABC):
    """Abstract base class for OCR providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the provider name."""
        pass

    @property
    @abstractmethod
    def provider_type(self) -> ProviderType:
        """Return the provider type enum."""
        pass

    @abstractmethod
    async def recognize(self, image_data: bytes, language: str = "auto") -> List[TextRegion]:
        """
        Perform OCR on image data and return text regions.

        Args:
            image_data: Raw image bytes (PNG/JPEG)
            language: Language code or "auto" for auto-detection

        Returns:
            List of TextRegion objects with detected text and positions
        """
        pass

    @abstractmethod
    def is_available(self, language: str = "auto") -> bool:
        """
        Check if OCR is available for the given language.

        Args:
            language: Language code to check

        Returns:
            True if the provider can handle this language
        """
        pass

    @abstractmethod
    def get_supported_languages(self) -> List[str]:
        """
        Return list of supported language codes.

        Returns:
            List of ISO 639-1 language codes
        """
        pass


class TranslationProvider(ABC):
    """Abstract base class for translation providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the provider name."""
        pass

    @property
    @abstractmethod
    def provider_type(self) -> ProviderType:
        """Return the provider type enum."""
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    async def translate_batch(self, texts: List[str], source_lang: str, target_lang: str) -> List[str]:
        """
        Translate multiple texts efficiently.

        Args:
            texts: List of texts to translate
            source_lang: Source language code
            target_lang: Target language code

        Returns:
            List of translated texts
        """
        pass

    @abstractmethod
    def is_available(self, source_lang: str, target_lang: str) -> bool:
        """
        Check if translation is available for the language pair.

        Args:
            source_lang: Source language code
            target_lang: Target language code

        Returns:
            True if the provider can handle this language pair
        """
        pass

    @abstractmethod
    def get_supported_languages(self) -> List[str]:
        """
        Return list of supported language codes.

        Returns:
            List of language codes
        """
        pass


def chunk_indices(texts: List[str], max_chars: int, max_items: Optional[int] = None,
                  sep_chars: int = 0) -> List[List[int]]:
    """The indices of the non-blank texts, in order, grouped into requests: each group's total length (every text
    plus sep_chars, e.g. 1 for the newline joining them) stays within max_chars and, if given, max_items texts.
    A text longer than max_chars gets a group of its own."""
    chunks: List[List[int]] = []
    cur: List[int] = []
    size = 0
    for i, t in enumerate(texts):
        if not t or not t.strip():
            continue
        n = len(t) + sep_chars
        if cur and (size + n > max_chars or (max_items is not None and len(cur) >= max_items)):
            chunks.append(cur)
            cur, size = [], 0
        cur.append(i)
        size += n
    if cur:
        chunks.append(cur)
    return chunks
