"""Which Unicode scripts text is written in: NLLB routes and checks lines with it (nllb_translate.py, and
nllb_worker.py in its own process, which is why this is a module of its own)."""

SCRIPT_RANGES = [
    ((0x0041, 0x005A), "Latin"),
    ((0x0061, 0x007A), "Latin"),
    ((0x00C0, 0x024F), "Latin"),
    ((0x1E00, 0x1EFF), "Latin"),
    ((0x0370, 0x03FF), "Greek"),
    ((0x1F00, 0x1FFF), "Greek"),
    ((0x0400, 0x052F), "Cyrillic"),
    ((0x0600, 0x06FF), "Arabic"),
    ((0x0750, 0x077F), "Arabic"),
    ((0xFB50, 0xFDFF), "Arabic"),
    ((0xFE70, 0xFEFF), "Arabic"),
    ((0x0900, 0x097F), "Devanagari"),
    ((0x0E00, 0x0E7F), "Thai"),
    ((0x3040, 0x309F), "Hiragana"),
    ((0x30A0, 0x30FF), "Katakana"),
    ((0xFF66, 0xFF9D), "Katakana"),
    ((0x3400, 0x4DBF), "Han"),
    ((0x4E00, 0x9FFF), "Han"),
    ((0xF900, 0xFAFF), "Han"),
    ((0x1100, 0x11FF), "Hangul"),
    ((0x3130, 0x318F), "Hangul"),
    ((0xAC00, 0xD7AF), "Hangul"),
]

# FLORES-200 code suffix -> scripts that text in that language may use
_SUFFIX_SCRIPTS = {
    "Latn": {"Latin"},
    "Cyrl": {"Cyrillic"},
    "Grek": {"Greek"},
    "Arab": {"Arabic"},
    "Deva": {"Devanagari"},
    "Thai": {"Thai"},
    "Hang": {"Hangul", "Han"},
    "Jpan": {"Hiragana", "Katakana", "Han"},
    "Hans": {"Han"},
    "Hant": {"Han"},
}

CJK_SCRIPTS = {"Hiragana", "Katakana", "Han"}


def script_of(char):
    cp = ord(char)
    for (lo, hi), script in SCRIPT_RANGES:
        if lo <= cp <= hi:
            return script
    return None


def letter_scripts(text):
    counts = {}
    for c in text:
        if not c.isalpha():
            continue
        script = script_of(c)
        if script:
            counts[script] = counts.get(script, 0) + 1
    return counts


def dominant_script(text, min_letters=2, min_ratio=0.5):
    total = sum(1 for c in text if c.isalpha())
    if total < min_letters:
        return None
    counts = letter_scripts(text)
    if not counts:
        return None
    script = max(counts, key=counts.get)
    if counts[script] / total >= min_ratio:
        return script
    return None


def flores_scripts(code):
    suffix = code.rsplit("_", 1)[-1] if code else ""
    return _SUFFIX_SCRIPTS.get(suffix, set())
