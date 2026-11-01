"""ProviderRegistry.configure: which OCR and translation providers the settings select."""
import unittest

from providers import ProviderRegistry


class Configure(unittest.TestCase):
    def prefs(self, **kw):
        pm = ProviderRegistry()
        pm.configure(**kw)
        return pm._ocr_provider_preference, pm._translation_provider_preference

    def test_defaults(self):
        self.assertEqual(self.prefs(), ("chrome_screen_ai", "google_web"))

    def test_saved_choices_win(self):
        self.assertEqual(self.prefs(ocr_provider="windows_ocr", translation_provider="nllb"), ("windows_ocr", "nllb"))


if __name__ == "__main__":
    unittest.main()
