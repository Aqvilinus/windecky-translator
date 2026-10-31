"""ProviderManager.configure: which OCR and translation providers the settings select."""
import unittest

from providers import ProviderManager


class Configure(unittest.TestCase):
    def prefs(self, **kw):
        pm = ProviderManager()
        pm.configure(**kw)
        return pm._ocr_provider_preference, pm._translation_provider_preference

    def test_defaults(self):
        self.assertEqual(self.prefs(), ("chromescreenai", "freegoogle"))

    def test_saved_choices_win(self):
        self.assertEqual(self.prefs(ocr_provider="ocrspace", translation_provider="ct2"), ("ocrspace", "ct2"))


if __name__ == "__main__":
    unittest.main()
