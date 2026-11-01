"""Clear cache leaves no translated lines on disk."""
import os

from providers.translation_cache import TranslationCache


def test_clearing_the_cache_empties_its_write_ahead_log(tmp_path):
    db = str(tmp_path / "cache.db")
    cache = TranslationCache(db)
    cache.put_many([(f"line {i}", f"Zeile {i}") for i in range(200)], "en", "de", 1, "google_web")
    assert cache.count() == 200
    cache.clear()
    assert cache.count() == 0
    wal = db + "-wal"
    assert not os.path.exists(wal) or os.path.getsize(wal) == 0
    cache.close()
