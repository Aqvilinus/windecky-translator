"""Label background colour of the Windows overlay (py_modules/winport/overlay.py _background)."""
import sys
import unittest


if sys.platform != "win32":
    raise unittest.SkipTest("winport is Windows-only")
try:
    from PIL import Image, ImageDraw
except ImportError:
    raise unittest.SkipTest("Pillow is not installed")

from winport.overlay import _background  # noqa: E402


class Background(unittest.TestCase):
    def test_median_of_the_ring_around_the_box(self):
        img = Image.new("RGB", (100, 60), (10, 20, 30))
        ImageDraw.Draw(img).rectangle((20, 20, 79, 39), fill=(250, 250, 250))  # the text, inside the box
        img.putpixel((18, 18), (255, 0, 0))  # one odd pixel in the ring doesn't move the median
        self.assertEqual(_background(img, (20, 20, 80, 40)), (10, 20, 30))

    def test_box_at_the_edge(self):
        img = Image.new("RGB", (50, 50), (1, 2, 3))
        self.assertEqual(_background(img, (0, 0, 50, 50)), None)
        self.assertEqual(_background(img, (0, 0, 40, 40)), (1, 2, 3))

    def test_rgba_frame(self):
        img = Image.new("RGBA", (40, 40), (5, 6, 7, 255))
        self.assertEqual(_background(img, (10, 10, 20, 20)), (5, 6, 7))

    def test_no_frame(self):
        self.assertIsNone(_background(None, (0, 0, 1, 1)))


if __name__ == "__main__":
    unittest.main()
