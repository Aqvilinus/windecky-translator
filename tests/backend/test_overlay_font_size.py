"""Label font size of the Windows overlay (py_modules/overlay.py fit_font_size): the wrapped text fits."""
import sys
import unittest

if sys.platform != "win32":
    raise unittest.SkipTest("Windows-only")

from overlay import LINE_SPACING, font_for, fit_font_size, wrap_text  # noqa: E402

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
                size = fit_font_size(text, width, height, max_size=64, min_size=8)
                font = font_for(text, size)
                lines = wrap_text(text, font, width)
                self.assertLessEqual(max(font.getlength(line) for line in lines), width)
                self.assertLessEqual(len(lines) * size * LINE_SPACING, height)

    def test_at_most_the_original_line_size(self):
        self.assertEqual(fit_font_size("Quit", 400, 40, max_size=30, min_size=8), 30)
