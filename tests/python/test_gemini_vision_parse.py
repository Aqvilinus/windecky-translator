"""Gemini Vision reply parsing (py_modules/providers/gemini_vision.py _parse_json_response)."""
import json
import unittest

import _paths  # noqa: F401
from providers.gemini_vision import _parse_json_response

A = {"text": "Press } to skip [", "translated_text": "x", "box_2d": [1, 2, 3, 4]}
B = {"text": "Next", "translated_text": "y", "box_2d": [5, 6, 7, 8]}


class ParseJsonResponse(unittest.TestCase):
    def test_plain_array(self):
        self.assertEqual(_parse_json_response(json.dumps([A, B])), [A, B])

    def test_regions_object(self):
        self.assertEqual(_parse_json_response(json.dumps({"regions": [A]})), [A])

    def test_markdown_fence(self):
        self.assertEqual(_parse_json_response("Here:\n```json\n" + json.dumps([A, B]) + "\n```"), [A, B])

    def test_embedded_in_prose(self):
        self.assertEqual(_parse_json_response("Sure! " + json.dumps([A, B]) + " Done."), [A, B])

    def test_think_tags_removed(self):
        self.assertEqual(_parse_json_response("<think>[1, 2]</think>" + json.dumps([B])), [B])

    def test_truncated_reply_keeps_complete_objects_with_brackets_in_text(self):
        # the old bracket counter lost both regions here: '}' and ']' inside the first text
        text = json.dumps([A, B])
        cut = text[: text.rindex('"y"')]
        self.assertEqual(_parse_json_response(cut), [A])
        cut = text[:-1]  # only the closing ']' missing
        self.assertEqual(_parse_json_response(cut), [A, B])

    def test_garbage(self):
        self.assertIsNone(_parse_json_response("no json here"))
        self.assertIsNone(_parse_json_response(""))


if __name__ == "__main__":
    unittest.main()
