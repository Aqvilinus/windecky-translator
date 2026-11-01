"""The SQLite cache of translations, by language pair and source text, each with the tier of the engine that made it."""

import re
import time
import sqlite3
import logging
import threading

logger = logging.getLogger(__name__)

# A request reuses a cached entry only if its tier is >= the selected provider's tier, so quality only flows downward
PROVIDER_TIERS = {
    "nllb": 1,
    "google_web": 2,
    "google_cloud": 3,
    "gemini_vision": 3,
    "llm": 3,
}

# When exceeded, the least recently used rows are dropped
MAX_ROWS = 50000

_SPACES = re.compile(r"[^\S\n]+")  # whitespace other than line breaks


def normalize(text):
    """Cache key of a source text: runs of spaces collapsed and blank lines dropped, but case and line breaks kept
    ("US" and "us", "Maße" and "Masse", a two-line text and its one-line join are different texts)."""
    lines = (_SPACES.sub(" ", line).strip() for line in text.replace("\r\n", "\n").split("\n"))
    return "\n".join(line for line in lines if line)


class TranslationCache:
    def __init__(self, db_path):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS translations (
                source_lang   TEXT NOT NULL,
                target_lang   TEXT NOT NULL,
                norm_text     TEXT NOT NULL,
                source_text   TEXT,
                translation   TEXT NOT NULL,
                tier          INTEGER NOT NULL,
                provider      TEXT,
                created_at    INTEGER,
                last_used_at  INTEGER,
                hit_count     INTEGER DEFAULT 0,
                PRIMARY KEY (source_lang, target_lang, norm_text)
            )
            """
        )
        self._conn.commit()

    def get_many(self, texts, source_lang, target_lang, min_tier):
        norm_by_input = {}
        for text in texts:
            if text and text.strip():
                norm_by_input[text] = normalize(text)
        if not norm_by_input:
            return {}

        unique_norms = list(set(norm_by_input.values()))
        placeholders = ",".join("?" for _ in unique_norms)
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT norm_text, translation FROM translations
                WHERE source_lang=? AND target_lang=? AND tier>=?
                  AND norm_text IN ({placeholders})
                """,
                [source_lang, target_lang, min_tier, *unique_norms],
            ).fetchall()

            if rows:
                hit_norms = [r[0] for r in rows]
                hit_placeholders = ",".join("?" for _ in hit_norms)
                self._conn.execute(
                    f"""
                    UPDATE translations
                    SET hit_count = hit_count + 1, last_used_at = ?
                    WHERE source_lang=? AND target_lang=?
                      AND norm_text IN ({hit_placeholders})
                    """,
                    [int(time.time()), source_lang, target_lang, *hit_norms],
                )
                self._conn.commit()

        translation_by_norm = {r[0]: r[1] for r in rows}
        return {
            text: translation_by_norm[norm]
            for text, norm in norm_by_input.items()
            if norm in translation_by_norm
        }

    def put_many(self, pairs, source_lang, target_lang, tier, provider):
        now = int(time.time())
        rows = []
        for text, translation in pairs:
            if not text or not text.strip() or not translation:
                continue
            rows.append((source_lang, target_lang, normalize(text), text,
                         translation, tier, provider, now, now))
        if not rows:
            return

        with self._lock:
            # Only a higher tier may overwrite
            self._conn.executemany(
                """
                INSERT INTO translations
                    (source_lang, target_lang, norm_text, source_text, translation,
                     tier, provider, created_at, last_used_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_lang, target_lang, norm_text) DO UPDATE SET
                    source_text = excluded.source_text,
                    translation = excluded.translation,
                    tier = excluded.tier,
                    provider = excluded.provider,
                    last_used_at = excluded.last_used_at
                WHERE excluded.tier > translations.tier
                """,
                rows,
            )
            self._conn.commit()
            self._evict_if_needed()

    def _evict_if_needed(self):
        count = self._conn.execute("SELECT COUNT(*) FROM translations").fetchone()[0]
        if count <= MAX_ROWS:
            return
        to_remove = count - MAX_ROWS
        self._conn.execute(
            """
            DELETE FROM translations WHERE rowid IN (
                SELECT rowid FROM translations ORDER BY last_used_at ASC LIMIT ?
            )
            """,
            [to_remove],
        )
        self._conn.commit()
        logger.info(f"Translation cache evicted {to_remove} least-used entries (cap {MAX_ROWS})")

    def clear(self):
        with self._lock:
            self._conn.execute("DELETE FROM translations")
            self._conn.commit()
            self._conn.execute("VACUUM")
            # the write-ahead log still holds the deleted lines until it is checkpointed: empty it too
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def count(self):
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM translations").fetchone()[0]

    def list_entries(self, limit):
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT COALESCE(source_text, norm_text), translation,
                       source_lang, target_lang, hit_count, created_at, provider
                FROM translations
                ORDER BY created_at DESC
                LIMIT ?
                """,
                [limit],
            ).fetchall()
        return [
            {"source": r[0], "translation": r[1], "sourceLang": r[2],
             "targetLang": r[3], "hits": r[4], "createdAt": r[5], "provider": r[6]}
            for r in rows
        ]

    def delete_entry(self, source_lang, target_lang, source_text):
        with self._lock:
            self._conn.execute(
                "DELETE FROM translations WHERE source_lang=? AND target_lang=? AND norm_text=?",
                [source_lang, target_lang, normalize(source_text)],
            )
            self._conn.commit()

    def close(self):
        with self._lock:
            self._conn.close()