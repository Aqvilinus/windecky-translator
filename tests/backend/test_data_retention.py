"""What the plugin leaves on disk: screenshots a crash left in the temp folder, cache lines after Clear."""
import os
import tempfile

from providers import chromescreenai_provider
from providers.translation_cache import TranslationCache


def test_leftover_ocr_screenshots_are_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    leftover = tmp_path / f"{chromescreenai_provider.INPUT_PREFIX}abc.png"
    other = tmp_path / "someone_elses.png"
    leftover.write_bytes(b"png")
    other.write_bytes(b"png")
    chromescreenai_provider.ChromeScreenAIProvider(model_dir=str(tmp_path))
    assert not leftover.exists() and other.exists()


def test_clearing_the_cache_empties_its_write_ahead_log(tmp_path):
    db = str(tmp_path / "cache.db")
    cache = TranslationCache(db)
    cache.put_many([(f"line {i}", f"Zeile {i}") for i in range(200)], "en", "de", 1, "freegoogle")
    assert cache.clear() == 200
    wal = db + "-wal"
    assert not os.path.exists(wal) or os.path.getsize(wal) == 0
    cache.close()
