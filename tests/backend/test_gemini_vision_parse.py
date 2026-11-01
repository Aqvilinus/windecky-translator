"""Gemini Vision reply parsing (py_modules/providers/gemini_vision.py _parse_regions)."""
import json
import unittest

from providers.gemini_vision import _parse_regions

A = {"text": "Press } to skip [", "translated_text": "x", "box_2d": [1, 2, 3, 4]}
B = {"text": "Next", "translated_text": "y", "box_2d": [5, 6, 7, 8]}


class ParseRegions(unittest.TestCase):
    def test_reply(self):
        self.assertEqual(_parse_regions(json.dumps([A, B])), [A, B])

    def test_truncated_reply_keeps_complete_objects_with_brackets_in_text(self):
        text = json.dumps([A, B])
        cut = text[: text.rindex('"y"')]
        self.assertEqual(_parse_regions(cut), [A])
        cut = text[:-1]  # only the closing ']' missing
        self.assertEqual(_parse_regions(cut), [A, B])

    def test_nothing_readable(self):
        self.assertEqual(_parse_regions(""), [])


if __name__ == "__main__":
    unittest.main()
