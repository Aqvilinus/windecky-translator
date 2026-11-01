"""Offline translation: the NLLB-200 1.3B model (CTranslate2, int8) in a worker (nllb_worker.py), and its download
from Hugging Face."""

import logging
import os
import re
import threading
import unicodedata
from typing import List

from .base import DownloadError, Downloader, TranslationError, TranslationProvider
from .unicode_scripts import CJK_SCRIPTS, dominant_script, flores_scripts
from .worker import Worker

logger = logging.getLogger(__name__)

_NLLB_CODES = {
    "en": "eng_Latn",
    "ja": "jpn_Jpan",
    "zh-CN": "zho_Hans",
    "zh-TW": "zho_Hant",
    "ko": "kor_Hang",
    "de": "deu_Latn",
    "fr": "fra_Latn",
    "es": "spa_Latn",
    "it": "ita_Latn",
    "pt": "por_Latn",
    "ru": "rus_Cyrl",
    "ar": "arb_Arab",
    "nl": "nld_Latn",
    "no": "nob_Latn",  # Norwegian Bokmål
    "pl": "pol_Latn",
    "tr": "tur_Latn",
    "uk": "ukr_Cyrl",
    "el": "ell_Grek",
    "fi": "fin_Latn",
    "th": "tha_Thai",
    "vi": "vie_Latn",
    "ro": "ron_Latn",
    "bg": "bul_Cyrl",
    "hi": "hin_Deva",
    "id": "ind_Latn",
    "hr": "hrv_Latn",
    "cs": "ces_Latn",
    "hu": "hun_Latn",
    "sv": "swe_Latn",
    "da": "dan_Latn",
}

REQUIRED_MODEL_FILES = ["model.bin", "sentencepiece.bpe.model", "config.json", "shared_vocabulary.txt"]
OPTIONAL_MODEL_FILES = ["tokenizer_config.json", "special_tokens_map.json"]

HF_REPO = "JustFrederik/nllb-200-distilled-1.3B-ct2-int8"
# A fixed commit (not "main") and each file's sha256: a changed upstream file is refused instead of installed
HF_COMMIT = "30c36268408177b0fce2bfcfa205d877accd327d"
HF_BASE_URL = f"https://huggingface.co/{HF_REPO}/resolve/{HF_COMMIT}/{{filename}}"
FILE_SHA256 = {
    "model.bin": "72d7533dc7a0e8f10f19a650d4e90faf9cbfa899db5411ad124bd5802bd91263",
    "sentencepiece.bpe.model": "14bb8dfb35c0ffdea7bc01e56cea38b9e3d5efcdcb9c251d6b40538e1aab555a",
    "config.json": "0c2f6fa2057c7264d052fb4a62ba3476eeae70487acddfa8e779a53a00cbf44c",
    "shared_vocabulary.txt": "a132a83330f45514c2476eb81d1d69b3c41762264d16ce0a7ea982e5d6c728e5",
    "tokenizer_config.json": "d1aa8c3697d3e35674f97b5b7e9c99d22b010f528e80140257d97316be90d044",
    "special_tokens_map.json": "992bd4ed610d644d6823081937bcc91bb8878dd556cea4ae5327f2480361330e",
}


class NLLBDownloader(Downloader):
    name = "nllb-200-distilled-1.3B"
    approx_size_mb = 1410
    required_files = tuple(REQUIRED_MODEL_FILES)

    def _install(self, staging_dir: str) -> None:
        for filename in REQUIRED_MODEL_FILES + OPTIONAL_MODEL_FILES:
            self._check_cancel()
            # model.bin is nearly all of the download: the bar follows it
            progress = self._set_progress if filename == "model.bin" else None
            try:
                digest = self._fetch(HF_BASE_URL.format(filename=filename), os.path.join(staging_dir, filename),
                                     progress=progress, timeout=30)
            except DownloadError as e:
                if filename in OPTIONAL_MODEL_FILES and "HTTP 404" in str(e):
                    continue  # an optional file the repo doesn't have
                raise
            if digest != FILE_SHA256[filename]:
                raise DownloadError(f"{filename} is damaged or changed upstream (hash mismatch)")


WORKER_TIMEOUT_SECONDS = 120

# UI strings NLLB mangles ("STEAM MENU" -> "СТОМ МЕНУ"): kept as they are
_SKIP_TRANSLATE_TOKENS = {
    "steam menu", "quick menu", "quick access", "main menu",
    "b back", "a select", "a confirm", "x confirm", "y menu",
    "escape back",
    # Controller letters / shortcuts
    "a", "b", "x", "y",
    "l1", "l2", "l3", "l4", "l5",
    "r1", "r2", "r3", "r4", "r5",
    "lb", "rb", "lt", "rt",
}

_SHORT_TEXT_CHAR_LIMIT = 20

# NLLB was trained on single sentences and the decoder is O(n^2) in length,
# so splitting long inputs is a real speed win. In-batch dedup covers the
# extra fragments.
_SPLIT_SENTENCES_CHAR_LIMIT = 60

_MIN_PIECE_CHARS = 5  # so "Mr." and "e.g." don't end a sentence
# End punctuation + whitespace (ASCII and CJK)
_SENTENCE_END_RE = re.compile(r"[.!?。！？]+[\s　]+")

# Comma/semicolon fallback for long prose without periods. Only runs when
# a sentence is still above _CLAUSE_SPLIT_MIN_CHARS after the first pass.
_CLAUSE_BREAK_RE = re.compile(r"[,;、，；][\s　]+")
_CLAUSE_SPLIT_MIN_CHARS = 80

_SENTENCE_ENDERS = set(".!?。！？।…")
_TRAILING_ENDERS = ".!?。！？।…"

_BULLET_RE = re.compile(r"^(?:[-*•·▪●‣◦›»]|\d{1,3}[.)])(?:\s|$)")

_SCRIPT_LANGS = {}
for _code, _nllb in _NLLB_CODES.items():
    for _script in flores_scripts(_nllb):
        _SCRIPT_LANGS.setdefault(_script, set()).add(_code)

_LID_MIN_LETTERS = 12
_PLUGIN_TO_LID = {"zh-CN": "zh", "zh-TW": "zh", "no": "nb"}


_ZERO_WIDTH_CHARS = "\u200b\u200c\u200d\u200e\u200f\ufeff"

_PUNCT_FOLD = {
    "‘": "'", "’": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
    "–": "-", "—": "-", "‒": "-", "−": "-",
    " ": " ", "　": " ",
}
_NORMALIZE_TABLE = str.maketrans(
    {**_PUNCT_FOLD, "\r": "\n", **{c: None for c in _ZERO_WIDTH_CHARS}}
)


def _normalize_unicode(src: str) -> str:
    return unicodedata.normalize("NFKC", src).translate(_NORMALIZE_TABLE)


def _is_only_punct_or_digits(s: str) -> bool:
    return all(c.isdigit() or c.isspace() or c in ".,;:!?-_()[]{}'\"" for c in s)


def _is_number_heavy(s: str) -> bool:
    """Mostly digits, at most 2 letters: "5 HP", "102", "3/10", etc"""
    alpha = sum(1 for c in s if c.isalpha())
    digit = sum(1 for c in s if c.isdigit())
    return digit > 0 and alpha <= 2


def _should_skip_translation(src: str) -> bool:
    stripped = src.strip()
    if not stripped:
        return True
    if len(stripped) > _SHORT_TEXT_CHAR_LIMIT:
        return False
    if stripped.lower() in _SKIP_TRANSLATE_TOKENS:
        return True
    if _is_only_punct_or_digits(stripped):
        return True
    if _is_number_heavy(stripped):
        return True
    return False


def _normalize_caps(src: str):
    """Lowercase short ALL-CAPS strings; NLLB handles cased text better.
    Caller re-uppercases the output."""
    stripped = src.strip()
    upper = sum(1 for c in stripped if c.isupper())
    cased = upper + sum(1 for c in stripped if c.islower())
    if cased >= 4 and upper / cased >= 0.9:
        return stripped.lower(), True
    return src, False


def _sentence_case(s: str) -> str:
    for i, c in enumerate(s):
        if c.isalpha():
            return s[:i] + c.upper() + s[i + 1:]
    return s


def _append_terminal_punct(frag: str):
    """NLLB invents continuations for unterminated input - so close every fragment"""
    stripped = frag.rstrip()
    if not stripped or stripped[-1] in _SENTENCE_ENDERS:
        return stripped, False
    if not stripped[-1].isalnum():
        return stripped, False
    script = dominant_script(stripped)
    if script in CJK_SCRIPTS:
        if len(stripped) <= 8:
            return stripped, False
        return stripped + "。", True
    if len(stripped.split()) <= 3:
        return stripped, False
    if script == "Devanagari":
        return stripped + "।", True
    return stripped + ".", True


def _soft_wrap_joiner(prev: str, line: str):
    """Joiner if `line` continues `prev`, else None."""
    if prev[-1] in _SENTENCE_ENDERS or prev.endswith(":"):
        return None
    if _BULLET_RE.match(line):
        return None
    if prev.endswith("-"):
        return ""
    first = line[0]
    if first.isalpha() and first.islower():
        return " "
    if prev.endswith(","):
        return " "
    # Wrapped label/title ending on a single capitalized word
    if (first.isalpha() and first.isupper()
            and prev[-1].isalpha() and prev[-1].islower()
            and len(line.split()) == 1):
        return " "
    pf = dominant_script(prev)
    if pf in CJK_SCRIPTS and dominant_script(line) in CJK_SCRIPTS and len(prev) >= 20:
        return ""
    return None


def _split_lines(text: str) -> List[str]:
    lines = [l.strip() for l in text.split("\n")]
    lines = [l for l in lines if l]
    if len(lines) <= 1:
        return lines
    merged = [lines[0]]
    for line in lines[1:]:
        prev = merged[-1]
        joiner = _soft_wrap_joiner(prev, line)
        if joiner is None:
            merged.append(line)
        elif joiner == "" and prev.endswith("-"):
            merged[-1] = prev[:-1] + line
        else:
            merged[-1] = prev + joiner + line
    return merged


def _lid_eligible(text: str) -> bool:
    letters = sum(1 for c in text if c.isalpha())
    if letters < _LID_MIN_LETTERS:
        return False
    if dominant_script(text) not in CJK_SCRIPTS and len(text.split()) < 2:
        return False
    return True


def _route_line(text: str, src_code: str, tgt_code: str):
    src_scripts = flores_scripts(_NLLB_CODES.get(src_code, ""))
    tgt_scripts = flores_scripts(_NLLB_CODES.get(tgt_code, ""))
    script = dominant_script(text)
    if script is None:
        return "translate", src_code
    if script in src_scripts:
        # Latin source can't be told from English (or a Latin target)
        if script == "Latin" and _lid_eligible(text):
            cands = list(dict.fromkeys(
                [src_code, "en"] + ([tgt_code] if script in tgt_scripts else [])
            ))
            if len(cands) >= 2:
                on = {c: ("translate", c) for c in cands}
                if tgt_code in on and tgt_code != src_code:
                    on[tgt_code] = ("passthrough", None)
                return "lid", {"cands": cands, "on": on,
                               "default": ("translate", src_code)}
        return "translate", src_code
    if script in tgt_scripts:
        # Already target language
        if script == "Latin" and tgt_code != "en" and _lid_eligible(text):
            return "lid", {"cands": [tgt_code, "en"],
                           "on": {"en": ("translate", "en"),
                                  tgt_code: ("passthrough", None)},
                           "default": ("passthrough", None)}
        return "passthrough", None
    # Latin text on a non-Latin source/target pair is almost always English
    # (Steam UI, changelogs)
    if script == "Latin":
        return "translate", "en"
    langs = sorted(_SCRIPT_LANGS.get(script, ()))
    if len(langs) == 1:
        return "translate", langs[0]
    if langs and _lid_eligible(text):
        return "lid", {"cands": langs,
                       "on": {c: ("translate", c) for c in langs},
                       "default": ("translate", src_code)}
    return "translate", src_code


def _build_frags(body: str, was_caps: bool) -> List[dict]:
    fragments = [body]
    if len(body) >= _SPLIT_SENTENCES_CHAR_LIMIT:
        split = _split_sentences(body)
        if len(split) > 1:
            fragments = split
    frags = []
    for f in fragments:
        if was_caps:
            f = _sentence_case(f)
        f, punct_added = _append_terminal_punct(f)
        frags.append({"text": f, "caps": was_caps,
                      "punct": punct_added, "idx": None})
    return frags


def _split_sentences(text: str) -> List[str]:
    text = text.strip()
    if not text:
        return []
    sentences = []
    start = 0
    for match in _SENTENCE_END_RE.finditer(text):
        end = match.end()
        candidate = text[start:end].rstrip()
        if len(candidate) < _MIN_PIECE_CHARS:
            continue
        sentences.append(candidate)
        start = end
    if start < len(text):
        tail = text[start:].rstrip()
        if tail:
            sentences.append(tail)

    result = []
    for s in sentences:
        if len(s) >= _CLAUSE_SPLIT_MIN_CHARS:
            clauses = _split_on_clauses(s)
            if len(clauses) > 1:
                result.extend(clauses)
                continue
        result.append(s)
    return result


def _split_on_clauses(text: str) -> List[str]:
    clauses = []
    start = 0
    for match in _CLAUSE_BREAK_RE.finditer(text):
        end = match.end()
        candidate = text[start:end].rstrip().rstrip(",;、，；")
        if len(candidate) < _MIN_PIECE_CHARS:
            continue
        clauses.append(candidate)
        start = end
    if start < len(text):
        tail = text[start:].rstrip()
        if tail:
            clauses.append(tail)
    return clauses


class NLLBTranslateProvider(TranslationProvider):
    """The model runs in a worker process, so it isn't reloaded for every request."""

    def __init__(self, model: NLLBDownloader):
        self._model = model
        self._loaded_model_dir = None
        self._persistent_mode = False

        self._worker = Worker("NLLB", os.path.join(os.path.dirname(__file__), "nllb_worker.py"),
                              env={"OMP_NUM_THREADS": "4", "MKL_NUM_THREADS": "4"})

    def _ensure_worker(self) -> bool:
        if self._worker.alive:
            return True
        self._loaded_model_dir = None
        # a persistent worker skips its idle timeout (nllb_worker.py)
        return self._worker.start(env={"CT2_PERSISTENT": "1" if self._persistent_mode else None})

    def _send_command(self, cmd: dict, timeout: float = WORKER_TIMEOUT_SECONDS) -> dict:
        reply = self._worker.request(cmd, timeout)
        if reply is None:  # the worker is stopped: its model is gone too
            self._loaded_model_dir = None
            return {"ok": False, "error": "the worker stopped or didn't answer (details in the plugin log)"}
        return reply

    def _load_model(self) -> dict:
        model_dir = self._model.target_dir
        if self._loaded_model_dir == model_dir:
            return {"ok": True}

        result = self._send_command({"cmd": "load", "model_dir": model_dir})
        if result.get("ok"):
            self._loaded_model_dir = model_dir
        else:
            self._loaded_model_dir = None
        return result

    @property
    def name(self) -> str:
        return "Offline (NLLB)"

    def is_available(self, source_lang: str, target_lang: str) -> bool:
        if source_lang == "auto":
            return False
        return self._model.is_installed()

    async def translate_batch(
        self, texts: List[str], source_lang: str, target_lang: str
    ) -> List[str]:
        import asyncio
        return await asyncio.to_thread(
            self._translate_batch_sync, texts, source_lang, target_lang
        )

    def _translate_batch_sync(
        self, texts: List[str], source_lang: str, target_lang: str
    ) -> List[str]:
        if not texts:
            return []

        if source_lang == "auto":
            raise TranslationError("Offline translation needs a source language: select one in plugin settings")

        src_nllb = _NLLB_CODES.get(source_lang)
        tgt_nllb = _NLLB_CODES.get(target_lang)
        if not src_nllb or not tgt_nllb:
            raise TranslationError(f"Offline translation does not support {source_lang} -> {target_lang}")

        if not self._model.is_installed():
            raise TranslationError("Offline model not found. Download it in plugin settings")

        if not self._ensure_worker():
            raise TranslationError("Offline translation could not start (details in the plugin log)")

        load_result = self._load_model()
        if not load_result.get("ok"):
            raise TranslationError(f"Offline model failed to load: {load_result['error']}")

        slots = []
        lines_meta = []
        for t in texts:
            normalized = _normalize_unicode(t)
            if _should_skip_translation(normalized):
                slots.append({"source": t, "kind": "skip", "start": 0, "end": 0})
                continue

            start = len(lines_meta)
            for li, line in enumerate(_split_lines(normalized)):
                sep = "" if li == 0 else "\n"
                if _should_skip_translation(line):
                    lines_meta.append({"orig": line, "sep": sep,
                                       "kind": "skip", "frags": []})
                    continue
                body, was_caps = _normalize_caps(line)
                # Route on the lowercased body: LID misreads ALL-CAPS text
                kind, route = _route_line(body, source_lang, target_lang)
                if kind == "passthrough":
                    lines_meta.append({"orig": line, "sep": sep,
                                       "kind": "passthrough", "frags": []})
                elif kind == "lid":
                    lines_meta.append({"orig": line, "sep": sep, "kind": "lid",
                                       "spec": route, "body": body,
                                       "caps": was_caps, "frags": []})
                else:
                    lines_meta.append({"orig": line, "sep": sep,
                                       "kind": "translate",
                                       "frags": _build_frags(body, was_caps),
                                       "tag": _NLLB_CODES.get(route) or src_nllb})
            slots.append({"source": t, "kind": "translate",
                          "start": start, "end": len(lines_meta)})

        pending = [lm for lm in lines_meta if lm["kind"] == "lid"]
        if pending:
            lid_maps = []
            lid_cands = []
            for lm in pending:
                m = {}
                for c in lm["spec"]["cands"]:
                    m.setdefault(_PLUGIN_TO_LID.get(c, c), c)
                lid_maps.append(m)
                lid_cands.append(sorted(m))
            resp = self._send_command({
                "cmd": "lid",
                "texts": [lm["body"] for lm in pending],
                "candidates": lid_cands,
            })
            langs = resp.get("langs") if resp.get("ok") else None
            for j, lm in enumerate(pending):
                detected = None
                if langs and langs[j]:
                    detected = lid_maps[j].get(langs[j])
                action = lm["spec"]["on"].get(detected) if detected else None
                if action is None:
                    action = lm["spec"]["default"]
                kind, code = action
                if detected:
                    logger.debug(f"  CT2 LID {detected} -> {action}: {lm['orig'][:80]}")
                if kind == "passthrough":
                    lm["kind"] = "passthrough"
                else:
                    lm["kind"] = "translate"
                    lm["tag"] = _NLLB_CODES.get(code) or src_nllb
                    lm["frags"] = _build_frags(lm["body"], lm["caps"])

        # Dedupe identical fragments (repeated UI strings, names, HP/Lv labels)
        unique_fragments = []
        unique_tags = []
        dedupe_index = {}
        for lm in lines_meta:
            for fe in lm["frags"]:
                key = (fe["text"], lm["tag"])
                idx = dedupe_index.get(key)
                if idx is None:
                    idx = len(unique_fragments)
                    dedupe_index[key] = idx
                    unique_fragments.append(fe["text"])
                    unique_tags.append(lm["tag"])
                fe["idx"] = idx

        skipped = sum(1 for s in slots if s["kind"] == "skip")
        logger.debug(
            f"CT2 translate: {len(texts)} inputs, {len(lines_meta)} lines "
            f"({len(unique_fragments)} unique fragments, {skipped} regions skipped), "
            f"{src_nllb} -> {tgt_nllb}"
        )
        for lm in lines_meta:
            if lm["kind"] == "passthrough":
                logger.debug(f"  CT2 line passthrough: {lm['orig'][:80]}")
            elif lm["kind"] == "translate" and lm["tag"] != src_nllb:
                logger.debug(f"  CT2 line re-tagged {lm['tag']}: {lm['orig'][:80]}")

        if unique_fragments:
            for i, f in enumerate(unique_fragments):
                logger.debug(
                    f"  CT2 input[{i}]: ({len(f)} chars, {unique_tags[i]}) {f[:200]}"
                )
            result = self._send_command({
                "cmd": "translate",
                "texts": unique_fragments,
                "src_langs": unique_tags,
                "tgt_lang": tgt_nllb,
            })
            if not result.get("ok"):
                raise TranslationError(f"Offline translation failed: {result.get('error')}")

            unique_translations = result["translations"]
            fallback_flags = result["fallbacks"]
            token_counts = result["token_counts"]
            logger.debug(f"  CT2 token counts: {token_counts}")
            for i, tc in enumerate(token_counts):
                # Output pinned at the decoding cap means the tail was cut off
                if tc["output"] >= min(32 + 3 * tc["input"], 256):
                    logger.warning(
                        f"  CT2 possible truncation on fragment {i}: {unique_fragments[i][:80]}"
                    )
        else:
            unique_translations = []
            fallback_flags = []

        translations = []
        for slot in slots:
            if slot["kind"] == "skip":
                translations.append(slot["source"])
                continue
            parts = []
            translated_lines = 0
            for lm in lines_meta[slot["start"]:slot["end"]]:
                if lm["kind"] != "translate":
                    parts.append(lm["sep"] + lm["orig"])
                    continue
                pieces = []
                failed = False
                for fe in lm["frags"]:
                    out = unique_translations[fe["idx"]]
                    if fallback_flags[fe["idx"]] or not out or not out.strip():
                        failed = True
                        break
                    if fe["punct"]:
                        out = out.rstrip().rstrip(_TRAILING_ENDERS).rstrip()
                    if fe["caps"]:
                        out = out.upper()
                    pieces.append(out)
                # keep the whole line when rejected
                if failed:
                    parts.append(lm["sep"] + lm["orig"])
                else:
                    translated_lines += 1
                    parts.append(lm["sep"] + " ".join(p for p in pieces if p))
            if translated_lines == 0:
                translations.append(slot["source"])
            else:
                translations.append("".join(parts))

        for i, t in enumerate(translations):
            src_len = len(texts[i]) if i < len(texts) else 0
            logger.debug(
                f"  CT2 output[{i}]: ({len(t)} chars, input was {src_len}) {t[:200]}"
            )

        return translations

    def _kill_worker(self):
        self._worker.stop()
        self._loaded_model_dir = None

    def set_persistent_mode(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._persistent_mode:
            return
        self._persistent_mode = enabled
        logger.info(f"CT2 persistent mode: {enabled}")
        if enabled:
            # Warm up so the first translate is faster
            threading.Thread(target=self._warmup_worker, daemon=True).start()
        else:
            self.shutdown()

    def _warmup_worker(self) -> None:
        if not self._persistent_mode:
            return
        if not self._model.is_installed():
            return
        # recycle a running worker so it gets CT2_PERSISTENT
        if self._worker.alive:
            self._kill_worker()
        if self._ensure_worker():
            self._load_model()

    def shutdown(self):
        self._worker.stop({"cmd": "shutdown"})
        self._loaded_model_dir = None

    def unload_current_model(self):
        if self._worker.alive:
            self._send_command({"cmd": "unload"})
            self._loaded_model_dir = None
