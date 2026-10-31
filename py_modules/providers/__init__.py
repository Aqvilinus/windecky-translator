# providers/__init__.py
# Provider factory and manager

import hashlib
import logging
import time
from typing import Dict, List, Optional

from .base import (
    OCRProvider,
    TranslationProvider,
    ProviderType,
    TextRegion,
    NetworkError,
    ApiKeyError,
    RateLimitError,
    OCRError,
    TranslationError,
)
from .google_ocr import GoogleVisionProvider
from .google_translate import GoogleTranslateProvider
from .ocrspace import OCRSpaceProvider
from .free_translate import FreeTranslateProvider
from .chromescreenai_provider import ChromeScreenAIProvider
from .gemini_vision import GeminiVisionProvider
from .ct2_translate import CT2TranslateProvider
from .llm_translate import LLMTranslateProvider
from .model_download import ModelDownload
from .nllb_downloader import NLLBDownload
from .screenai_downloader import ScreenAIDownload

logger = logging.getLogger(__name__)

_REACHABILITY_TTL = 4.0

_WEB_OCR_PROVIDERS = {"gemini_vision", "googlecloud", "ocrspace"}
_WEB_TRANSLATION_PROVIDERS = {"googlecloud", "freegoogle", "llm"}

# Export all public classes
__all__ = [
    'OCRProvider',
    'TranslationProvider',
    'ProviderType',
    'TextRegion',
    'NetworkError',
    'ApiKeyError',
    'RateLimitError',
    'OCRError',
    'TranslationError',
    'GoogleVisionProvider',
    'GoogleTranslateProvider',
    'OCRSpaceProvider',
    'FreeTranslateProvider',
    'ChromeScreenAIProvider',
    'GeminiVisionProvider',
    'CT2TranslateProvider',
    'ProviderManager',
]


# The frontend's OCR engine ids
OCR_PROVIDER_TYPES = {
    "chromescreenai": ProviderType.CHROME_SCREEN_AI,
    "windows_ocr": ProviderType.WINDOWS_OCR,
    "ocrspace": ProviderType.OCR_SPACE,
    "googlecloud": ProviderType.GOOGLE,
    "gemini_vision": ProviderType.GEMINI_VISION,
}


class ProviderManager:
    """Factory and manager for OCR and Translation providers."""

    def __init__(self):
        """Initialize the provider manager."""
        # Provider instances (created on demand)
        self._ocr_providers = {}
        self._translation_providers = {}

        # Configuration
        self._google_api_key = ""
        self._gemini_api_key = ""
        self._gemini_model = "gemini-3.5-flash"
        self._gemini_target_language = "en"
        self._ocr_provider_preference = "chromescreenai"  # see OCR_PROVIDER_TYPES
        self._translation_provider_preference = "freegoogle"  # "freegoogle", "googlecloud", or "ct2"
        # main.py _sync_workers decides: the worker of the chosen local engine stays up between requests
        self._chromescreenai_persistent_mode = False
        self._ct2_persistent_mode = False

        # The models the user downloads in the settings, by kind: "nllb" (offline translation), "chromescreenai"
        # (on-device OCR); configure() creates them with their folders
        self.downloads: Dict[str, ModelDownload] = {}

        self._reachability_cache: dict = {}

        # AI translation settings (applied to the provider when it's created)
        self._llm_config: dict = {}

        logger.debug("ProviderManager initialized")

    def configure(
        self,
        google_api_key: str = "",
        gemini_api_key: str = "",
        ocr_provider: str = "",
        translation_provider: str = "",
        ct2_models_dir: str = "",
        screenai_models_dir: str = "",
    ) -> None:
        """
        Configure provider preferences.

        Args:
            google_api_key: Google Cloud API key (only needed for googlecloud providers)
            ocr_provider: OCR provider preference, a key of OCR_PROVIDER_TYPES
            translation_provider: Translation provider preference - "freegoogle", "googlecloud", or "ct2"
            ct2_models_dir: Directory for CT2 translation model storage
        """
        if ct2_models_dir and "nllb" not in self.downloads:
            self.downloads["nllb"] = NLLBDownload(ct2_models_dir)
        if screenai_models_dir and "chromescreenai" not in self.downloads:
            self.downloads["chromescreenai"] = ScreenAIDownload(screenai_models_dir)
        self._google_api_key = google_api_key
        self._gemini_api_key = gemini_api_key

        if ocr_provider:
            self._ocr_provider_preference = ocr_provider
        if translation_provider:
            self._translation_provider_preference = translation_provider

        # Update Google Cloud providers with new API key
        if ProviderType.GOOGLE in self._ocr_providers:
            self._ocr_providers[ProviderType.GOOGLE].set_api_key(google_api_key)
        if ProviderType.GOOGLE in self._translation_providers:
            self._translation_providers[ProviderType.GOOGLE].set_api_key(google_api_key)

        # Update Gemini Vision provider with new API key
        if ProviderType.GEMINI_VISION in self._ocr_providers:
            self._ocr_providers[ProviderType.GEMINI_VISION].set_api_key(gemini_api_key)

        logger.debug(
            f"Provider config updated: ocr_provider={self._ocr_provider_preference}, "
            f"translation_provider={self._translation_provider_preference}, "
            f"google_api_key_set={bool(google_api_key)}"
        )

    def configure_llm(self, backend: str = "", keys: Optional[dict] = None, models: Optional[dict] = None,
                      custom_url: Optional[str] = None) -> None:
        """AI translation: backend ("gemini", "groq", "custom"), API keys and models per backend, custom server URL."""
        cfg = self._llm_config
        if backend:
            cfg["backend"] = backend
        cfg.setdefault("keys", {}).update(keys or {})
        cfg.setdefault("models", {}).update(models or {})
        if custom_url is not None:
            cfg["custom_url"] = custom_url
        llm = self._translation_providers.get(ProviderType.LLM)
        if llm:
            llm.configure(backend=backend, keys=keys, models=models, custom_url=custom_url)
        self._reachability_cache.clear()

    def get_llm_provider(self) -> LLMTranslateProvider:
        return self.get_translation_provider(ProviderType.LLM)

    def set_gemini_target_language(self, target_lang: str) -> None:
        """Update the Gemini Vision provider's target language before each OCR call."""
        self._gemini_target_language = target_lang
        gemini = self._ocr_providers.get(ProviderType.GEMINI_VISION)
        if gemini:
            gemini.set_target_language(target_lang)

    def set_gemini_model(self, model: str) -> None:
        """Update the Gemini model. Recreates the provider on next use if model changed."""
        if self._gemini_model != model:
            self._gemini_model = model
            # Remove cached provider so it gets recreated with the new model
            self._ocr_providers.pop(ProviderType.GEMINI_VISION, None)

    def set_chromescreenai_persistent_mode(self, enabled: bool) -> None:
        """Keep the Chrome Screen AI worker running between requests (True), or stop it (False)."""
        self._chromescreenai_persistent_mode = bool(enabled)
        provider = (self.get_ocr_provider(ProviderType.CHROME_SCREEN_AI) if enabled
                    else self._ocr_providers.get(ProviderType.CHROME_SCREEN_AI))
        if provider:
            provider.set_persistent_mode(self._chromescreenai_persistent_mode)

    def set_ct2_persistent_mode(self, enabled: bool) -> None:
        """Keep the offline NLLB worker running between requests (True), or stop it (False)."""
        self._ct2_persistent_mode = bool(enabled)
        provider = (self.get_translation_provider(ProviderType.CT2) if enabled
                    else self._translation_providers.get(ProviderType.CT2))
        if provider:
            provider.set_persistent_mode(self._ct2_persistent_mode)

    def get_ocr_provider(
        self,
        provider_type: Optional[ProviderType] = None
    ) -> Optional[OCRProvider]:
        """
        Get OCR provider, creating if necessary.

        Args:
            provider_type: Specific provider type, or None for default based on preference

        Returns:
            OCRProvider instance or None
        """
        if provider_type is None:
            provider_type = OCR_PROVIDER_TYPES.get(self._ocr_provider_preference, ProviderType.CHROME_SCREEN_AI)

        if provider_type not in self._ocr_providers:
            if provider_type == ProviderType.OCR_SPACE:
                self._ocr_providers[provider_type] = OCRSpaceProvider()
            elif provider_type == ProviderType.GOOGLE:
                self._ocr_providers[provider_type] = GoogleVisionProvider(
                    self._google_api_key
                )
            elif provider_type == ProviderType.GEMINI_VISION:
                provider = GeminiVisionProvider(
                    api_key=self._gemini_api_key,
                    model=self._gemini_model,
                )
                provider.set_target_language(self._gemini_target_language)
                self._ocr_providers[provider_type] = provider
            elif provider_type == ProviderType.CHROME_SCREEN_AI:
                screenai = self.downloads.get("chromescreenai")
                provider = ChromeScreenAIProvider(model_dir=screenai.resources_dir if screenai else "")
                if self._chromescreenai_persistent_mode:
                    provider.set_persistent_mode(True)
                self._ocr_providers[provider_type] = provider
            elif provider_type == ProviderType.WINDOWS_OCR:
                from .windows_ocr import WindowsOCRProvider  # Windows only (pywinrt)
                self._ocr_providers[provider_type] = WindowsOCRProvider()

        return self._ocr_providers.get(provider_type)

    def get_translation_provider(
        self,
        provider_type: Optional[ProviderType] = None
    ) -> Optional[TranslationProvider]:
        """
        Get translation provider, creating if necessary.

        Args:
            provider_type: Specific provider type, or None for default based on preference

        Returns:
            TranslationProvider instance or None
        """
        if provider_type is None:
            # Use translation provider preference (independent of OCR choice)
            if self._translation_provider_preference == "googlecloud":
                provider_type = ProviderType.GOOGLE
            elif self._translation_provider_preference == "ct2":
                provider_type = ProviderType.CT2
            elif self._translation_provider_preference == "llm":
                provider_type = ProviderType.LLM
            else:
                provider_type = ProviderType.FREE_GOOGLE

        if provider_type not in self._translation_providers:
            if provider_type == ProviderType.FREE_GOOGLE:
                self._translation_providers[provider_type] = FreeTranslateProvider()
            elif provider_type == ProviderType.LLM:
                # shares the free provider, so a Google pause after a 429 holds for both
                llm = LLMTranslateProvider(fallback=self.get_translation_provider(ProviderType.FREE_GOOGLE))
                cfg = self._llm_config
                llm.configure(backend=cfg.get("backend", ""), keys=cfg.get("keys"), models=cfg.get("models"),
                              custom_url=cfg.get("custom_url", ""))
                self._translation_providers[provider_type] = llm
            elif provider_type == ProviderType.GOOGLE:
                self._translation_providers[provider_type] = GoogleTranslateProvider(
                    self._google_api_key
                )
            elif provider_type == ProviderType.CT2:
                if "nllb" in self.downloads:
                    provider = CT2TranslateProvider(self.downloads["nllb"])
                    if self._ct2_persistent_mode:
                        provider.set_persistent_mode(True)
                    self._translation_providers[provider_type] = provider

        return self._translation_providers.get(provider_type)

    async def recognize_text(
        self,
        image_data: bytes,
        language: str = "auto"
    ) -> List[TextRegion]:
        """
        Perform OCR with automatic provider selection.

        Args:
            image_data: Raw image bytes
            language: Language code or "auto"

        Returns:
            List of TextRegion objects
        """
        provider = self.get_ocr_provider()
        if not provider or not provider.is_available(language):
            raise OCRError(f"{provider.name if provider else 'The OCR engine'} is unavailable")
        logger.debug(f"Using {provider.name} for OCR")
        return await provider.recognize(image_data, language)

    async def translate_text(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str
    ) -> List[str]:
        """
        Perform translation with automatic provider selection.

        Args:
            texts: List of texts to translate
            source_lang: Source language code
            target_lang: Target language code

        Returns:
            List of translated texts
        """
        if not texts:
            return []

        provider = self.get_translation_provider()
        if not provider or not provider.is_available(source_lang, target_lang):
            raise TranslationError(f"{provider.name if provider else 'The translator'} is unavailable for "
                                   f"{source_lang} -> {target_lang}")
        logger.debug(f"Using {provider.name} for translation")
        return await provider.translate_batch(texts, source_lang, target_lang)

    def get_provider_status(self) -> dict:
        """
        Get current provider configuration and availability status.

        Returns:
            Dictionary with provider status information
        """
        ocr_provider = self.get_ocr_provider()
        trans_provider = self.get_translation_provider()

        status = {
            "ocr_provider_preference": self._ocr_provider_preference,
            "translation_provider_preference": self._translation_provider_preference,
            "google_api_configured": bool(self._google_api_key),
            "gemini_api_configured": bool(self._gemini_api_key),
            "ocr_provider": ocr_provider.name if ocr_provider else "None",
            "translation_provider": trans_provider.name if trans_provider else "None",
            "ocr_available": ocr_provider.is_available() if ocr_provider else False,
            "translation_available": trans_provider.is_available("auto", "en") if trans_provider else False,
        }

        # Add OCR.space usage stats if using ocrspace (OCR.space) provider
        if self._ocr_provider_preference == "ocrspace" and ocr_provider:
            status["ocr_usage"] = ocr_provider.get_usage_stats()

        llm = self._translation_providers.get(ProviderType.LLM)
        if llm:
            status["llm_backend"] = llm.backend
            status["llm_model"] = llm.model
            status["llm_configured"] = llm.is_configured()
            status["llm_last_error"] = llm.last_error

        for kind in ("nllb", "chromescreenai"):
            s = self.model_status(kind) or {}
            status[f"{kind}_downloaded"] = bool(s.get("downloaded"))
            status[f"{kind}_downloading"] = bool(s.get("downloading"))
            status[f"{kind}_progress"] = float(s.get("progress") or 0)

        return status

    async def check_web_reachability(self) -> dict:
        """Probe reachability of the currently selected web providers."""
        ocr_pref = self._ocr_provider_preference
        trans_pref = self._translation_provider_preference

        result = {"ocr": None, "translation": None, "checked_at": time.time()}

        # gemini_vision is a combined OCR+translation call; probe once and mirror
        if ocr_pref == "gemini_vision":
            r = await self._probe_cached("gemini_vision", "ocr", self._gemini_api_key)
            result["ocr"] = r
            result["translation"] = r
            return result

        if ocr_pref in _WEB_OCR_PROVIDERS:
            key = self._google_api_key if ocr_pref == "googlecloud" else ""
            result["ocr"] = await self._probe_cached(ocr_pref, "ocr", key)

        if trans_pref in _WEB_TRANSLATION_PROVIDERS:
            key = self._google_api_key if trans_pref == "googlecloud" else ""
            result["translation"] = await self._probe_cached(trans_pref, "translation", key)

        return result

    async def _probe_cached(self, provider: str, kind: str, api_key: str) -> dict:
        key_hash = hashlib.sha256((api_key or "").encode("utf-8")).hexdigest()[:16]
        cache_key = (provider, kind, key_hash)
        cached = self._reachability_cache.get(cache_key)
        now = time.time()
        if cached and (now - cached[0]) < _REACHABILITY_TTL:
            return cached[1]

        ok, reason = await self._probe_provider(provider, kind)
        result = {"ok": ok, "reason": reason, "provider": provider}
        self._reachability_cache[cache_key] = (now, result)
        return result

    async def _probe_provider(self, provider: str, kind: str) -> tuple:
        try:
            if provider == "gemini_vision":
                p = self.get_ocr_provider(ProviderType.GEMINI_VISION)
            elif provider == "googlecloud" and kind == "ocr":
                p = self.get_ocr_provider(ProviderType.GOOGLE)
            elif provider == "googlecloud" and kind == "translation":
                p = self.get_translation_provider(ProviderType.GOOGLE)
            elif provider == "ocrspace":
                p = self.get_ocr_provider(ProviderType.OCR_SPACE)
            elif provider == "freegoogle":
                p = self.get_translation_provider(ProviderType.FREE_GOOGLE)
            elif provider == "llm":
                p = self.get_translation_provider(ProviderType.LLM)
            else:
                return False, f"Unknown provider ({provider})"

            if p is None:
                return False, "Provider unavailable"

            return await p.test_network()
        except Exception as e:
            logger.warning(f"Reachability probe failed for {provider}/{kind}: {e}")
            return False, f"Probe failed: {type(e).__name__}"

    # -- the downloadable models (self.downloads)

    def model_installed(self, kind: str) -> bool:
        d = self.downloads.get(kind)
        return bool(d and d.is_installed())

    def model_status(self, kind: str) -> Optional[dict]:
        d = self.downloads.get(kind)
        return d.status() if d else None

    def download_model(self, kind: str) -> bool:
        d = self.downloads.get(kind)
        return bool(d and d.start())

    def cancel_model_download(self, kind: str) -> None:
        if kind in self.downloads:
            self.downloads[kind].cancel()

    def clear_model_error(self, kind: str) -> None:
        if kind in self.downloads:
            self.downloads[kind].clear_error()

    def delete_model(self, kind: str) -> bool:
        """Delete a downloaded model, after stopping the engine that has it open."""
        if kind not in self.downloads:
            return False
        if kind == "nllb":
            ct2 = self._translation_providers.get(ProviderType.CT2)
            if ct2:
                ct2.unload_current_model()
        elif kind == "chromescreenai":
            screenai = self._ocr_providers.pop(ProviderType.CHROME_SCREEN_AI, None)  # rechecks availability later
            if screenai:
                screenai.stop_worker()
        return self.downloads[kind].delete()

    def shutdown(self):
        ct2 = self._translation_providers.get(ProviderType.CT2)
        if ct2:
            ct2.shutdown()
        screenai = self._ocr_providers.get(ProviderType.CHROME_SCREEN_AI)
        if screenai:
            screenai.stop_worker()
