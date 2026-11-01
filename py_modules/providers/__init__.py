"""ProviderRegistry: creates the provider the settings choose by its id, keeps it, and owns the model downloads."""

import hashlib
import logging
import time
from typing import Dict, List, Optional

from .base import (
    OCRProvider,
    TranslationProvider,
    TextRegion,
    NetworkError,
    ApiKeyError,
    RateLimitError,
    OCRError,
    TranslationError,
    Downloader,
)
from .google_cloud_vision import GoogleCloudVisionProvider
from .google_cloud_translate import GoogleCloudTranslateProvider
from .google_web_translate import GoogleWebTranslateProvider
from .chrome_screen_ai import ChromeScreenAIDownloader, ChromeScreenAIProvider
from .gemini_vision import GeminiVisionProvider
from .nllb_translate import NLLBDownloader, NLLBTranslateProvider
from .llm_translate import LLMTranslateProvider

logger = logging.getLogger(__name__)

_REACHABILITY_CACHE_SECONDS = 4.0

_WEB_OCR_PROVIDERS = {"gemini_vision", "googlecloud"}
_WEB_TRANSLATION_PROVIDERS = {"googlecloud", "freegoogle", "llm"}

__all__ = [
    'OCRProvider',
    'TranslationProvider',
    'TextRegion',
    'NetworkError',
    'ApiKeyError',
    'RateLimitError',
    'OCRError',
    'TranslationError',
    'GoogleCloudVisionProvider',
    'GoogleCloudTranslateProvider',
    'GoogleWebTranslateProvider',
    'ChromeScreenAIProvider',
    'GeminiVisionProvider',
    'NLLBTranslateProvider',
    'ProviderRegistry',
]




class ProviderRegistry:
    """The OCR and translation providers by id, created on first use with the settings main.py passes in."""

    def __init__(self):
        self._ocr_providers = {}
        self._translation_providers = {}

        self._google_api_key = ""
        self._gemini_api_key = ""
        self._gemini_model = "gemini-3.5-flash"
        self._gemini_target_language = "en"
        self._ocr_provider_preference = "chromescreenai"  # engine ids as the frontend names them (main.py)
        self._translation_provider_preference = "freegoogle"
        # main.py _sync_workers decides: the worker of the chosen local engine stays up between requests
        self._chromescreenai_persistent_mode = False
        self._ct2_persistent_mode = False

        # The models the user downloads in the settings, by kind: "nllb" (offline translation), "chromescreenai"
        # (on-device OCR); configure() creates them with their folders
        self.downloads: Dict[str, Downloader] = {}

        self._reachability_cache: dict = {}

        # configure_llm()'s settings, for the provider when it's created
        self._llm_config: dict = {}

        logger.debug("ProviderRegistry initialized")

    def configure(
        self,
        google_api_key: str = "",
        gemini_api_key: str = "",
        ocr_provider: str = "",
        translation_provider: str = "",
        ct2_models_dir: str = "",
        screenai_models_dir: str = "",
    ) -> None:
        if ct2_models_dir and "nllb" not in self.downloads:
            self.downloads["nllb"] = NLLBDownloader(ct2_models_dir)
        if screenai_models_dir and "chromescreenai" not in self.downloads:
            self.downloads["chromescreenai"] = ChromeScreenAIDownloader(screenai_models_dir)
        self._google_api_key = google_api_key
        self._gemini_api_key = gemini_api_key

        if ocr_provider:
            self._ocr_provider_preference = ocr_provider
        if translation_provider:
            self._translation_provider_preference = translation_provider

        if "googlecloud" in self._ocr_providers:
            self._ocr_providers["googlecloud"].set_api_key(google_api_key)
        if "googlecloud" in self._translation_providers:
            self._translation_providers["googlecloud"].set_api_key(google_api_key)

        if "gemini_vision" in self._ocr_providers:
            self._ocr_providers["gemini_vision"].set_api_key(gemini_api_key)

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
        llm = self._translation_providers.get("llm")
        if llm:
            llm.configure(backend=backend, keys=keys, models=models, custom_url=custom_url)
        self._reachability_cache.clear()

    def get_llm_provider(self) -> LLMTranslateProvider:
        return self.get_translation_provider("llm")

    def set_gemini_target_language(self, target_lang: str) -> None:
        """Update the Gemini Vision provider's target language before each OCR call."""
        self._gemini_target_language = target_lang
        gemini = self._ocr_providers.get("gemini_vision")
        if gemini:
            gemini.set_target_language(target_lang)

    def set_gemini_model(self, model: str) -> None:
        if self._gemini_model != model:
            self._gemini_model = model
            # recreated with the new model on next use
            self._ocr_providers.pop("gemini_vision", None)

    def set_chromescreenai_persistent_mode(self, enabled: bool) -> None:
        """Keep the Chrome Screen AI worker running between requests (True), or stop it (False)."""
        self._chromescreenai_persistent_mode = bool(enabled)
        provider = (self.get_ocr_provider("chromescreenai") if enabled
                    else self._ocr_providers.get("chromescreenai"))
        if provider:
            provider.set_persistent_mode(self._chromescreenai_persistent_mode)

    def set_ct2_persistent_mode(self, enabled: bool) -> None:
        """Keep the offline NLLB worker running between requests (True), or stop it (False)."""
        self._ct2_persistent_mode = bool(enabled)
        provider = (self.get_translation_provider("ct2") if enabled
                    else self._translation_providers.get("ct2"))
        if provider:
            provider.set_persistent_mode(self._ct2_persistent_mode)

    def get_ocr_provider(self, engine: Optional[str] = None) -> Optional[OCRProvider]:
        """The OCR provider for an engine id (default: the chosen one), created on first use."""
        engine = engine or self._ocr_provider_preference
        if engine not in self._ocr_providers:
            provider = self._make_ocr_provider(engine)
            if provider is None:
                return None
            self._ocr_providers[engine] = provider
        return self._ocr_providers[engine]

    def _make_ocr_provider(self, engine: str) -> Optional[OCRProvider]:
        if engine == "chromescreenai":
            screenai = self.downloads.get("chromescreenai")
            provider = ChromeScreenAIProvider(model_dir=screenai.resources_dir if screenai else "")
            if self._chromescreenai_persistent_mode:
                provider.set_persistent_mode(True)
            return provider
        if engine == "windows_ocr":
            from .windows_ocr import WindowsOCRProvider  # winrt, loaded only when chosen
            return WindowsOCRProvider()
        if engine == "googlecloud":
            return GoogleCloudVisionProvider(self._google_api_key)
        if engine == "gemini_vision":
            provider = GeminiVisionProvider(api_key=self._gemini_api_key, model=self._gemini_model)
            provider.set_target_language(self._gemini_target_language)
            return provider
        logger.error(f"Unknown OCR engine: {engine}")
        return None

    def get_translation_provider(self, engine: Optional[str] = None) -> Optional[TranslationProvider]:
        """The translation provider for an engine id (default: the chosen one), created on first use."""
        engine = engine or self._translation_provider_preference
        if engine not in self._translation_providers:
            provider = self._make_translation_provider(engine)
            if provider is None:
                return None
            self._translation_providers[engine] = provider
        return self._translation_providers[engine]

    def _make_translation_provider(self, engine: str) -> Optional[TranslationProvider]:
        if engine == "freegoogle":
            return GoogleWebTranslateProvider()
        if engine == "googlecloud":
            return GoogleCloudTranslateProvider(self._google_api_key)
        if engine == "llm":
            # shares the free provider, so a Google pause after a 429 holds for both
            llm = LLMTranslateProvider(fallback=self.get_translation_provider("freegoogle"))
            cfg = self._llm_config
            llm.configure(backend=cfg.get("backend", ""), keys=cfg.get("keys"), models=cfg.get("models"),
                          custom_url=cfg.get("custom_url", ""))
            return llm
        if engine == "ct2":
            if "nllb" not in self.downloads:
                return None
            provider = NLLBTranslateProvider(self.downloads["nllb"])
            if self._ct2_persistent_mode:
                provider.set_persistent_mode(True)
            return provider
        logger.error(f"Unknown translation engine: {engine}")
        return None

    async def recognize_text(
        self,
        image_data: bytes,
        language: str = "auto"
    ) -> List[TextRegion]:
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
        if not texts:
            return []

        provider = self.get_translation_provider()
        if not provider or not provider.is_available(source_lang, target_lang):
            raise TranslationError(f"{provider.name if provider else 'The translator'} is unavailable for "
                                   f"{source_lang} -> {target_lang}")
        logger.debug(f"Using {provider.name} for translation")
        return await provider.translate_batch(texts, source_lang, target_lang)

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
        if cached and (now - cached[0]) < _REACHABILITY_CACHE_SECONDS:
            return cached[1]

        ok, reason = await self._probe_provider(provider, kind)
        result = {"ok": ok, "reason": reason, "provider": provider}
        self._reachability_cache[cache_key] = (now, result)
        return result

    async def _probe_provider(self, provider: str, kind: str) -> tuple:
        try:
            p = self.get_ocr_provider(provider) if kind == "ocr" else self.get_translation_provider(provider)
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
            ct2 = self._translation_providers.get("ct2")
            if ct2:
                ct2.unload_current_model()
        elif kind == "chromescreenai":
            screenai = self._ocr_providers.pop("chromescreenai", None)  # rechecks availability later
            if screenai:
                screenai.stop_worker()
        return self.downloads[kind].delete()

    def shutdown(self):
        ct2 = self._translation_providers.get("ct2")
        if ct2:
            ct2.shutdown()
        screenai = self._ocr_providers.get("chromescreenai")
        if screenai:
            screenai.stop_worker()
