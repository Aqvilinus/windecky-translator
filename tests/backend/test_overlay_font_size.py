"""Label font size of the Windows overlay (py_modules/winport/overlay.py font_size_for): the wrapped text fits."""
import sys
import unittest

if sys.platform != "win32":
    raise unittest.SkipTest("winport is Windows-only")

from winport.overlay import LINE_SPACING, font_for, font_size_for, wrap  # noqa: E402

CASES = [  # text, width, height of the label's room
    ("Продолжить", 230, 40),
    ("варлы беспокоятся. Отдохнуть здесь или идти дальше?", 640, 43),
    ("Ваш караван достиг края замёрзшего моря, и варлы беспокоятся. Отдохнуть здесь или идти дальше?", 400, 120),
    ("Сага о Знамени 3", 310, 104),
    ("继续你的旅程", 200, 40),
]


class FontSize(unittest.TestCase):
    def test_wrapped_text_fits_its_room(self):
        for text, width, height in CASES:
            with self.subTest(text=text):
                size = font_size_for(text, width, height, max_size=64, min_size=8)
                font = font_for(text, size)
                lines = wrap(text, font, width)
                self.assertLessEqual(max(font.getlength(line) for line in lines), width)
                self.assertLessEqual(len(lines) * size * LINE_SPACING, height)

    def test_at_most_the_original_line_size(self):
        self.assertEqual(font_size_for("Quit", 400, 40, max_size=30, min_size=8), 30)
