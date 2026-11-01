"""Web OCR engines get the screenshot as JPEG (providers/base.py to_jpeg): a fraction of the PNG, same size."""
import asyncio
import io
import json
import random

from PIL import Image, ImageDraw

from providers.base import to_jpeg
from providers.gemini_vision import GeminiVisionProvider


def screenshot_png(width=1920, height=1080):
    """A game-like frame: a noisy background with text-like strokes (a flat image would compress well as PNG)."""
    rnd = random.Random(1)
    img = Image.effect_noise((width, height), 40).convert("RGB")
    draw = ImageDraw.Draw(img)
    for _ in range(300):
        x, y = rnd.randrange(width - 200), rnd.randrange(height - 20)
        draw.text((x, y), "Press A to continue", fill=(255, 255, 255))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def test_to_jpeg_is_smaller_and_keeps_the_size():
    png = screenshot_png()
    jpeg = to_jpeg(png)
    sent = Image.open(io.BytesIO(jpeg))
    assert sent.format == "JPEG" and sent.size == (1920, 1080)
    assert len(jpeg) < len(png) / 2


def test_gemini_vision_uploads_the_jpeg_and_maps_boxes_to_the_screenshot():
    provider = GeminiVisionProvider(api_key="test-key")
    sent = []

    async def call_api(image_data, prompt):
        sent.append(image_data)
        return json.dumps({"regions": [{"text": "Hallo", "translated_text": "Hello", "box_2d": [500, 500, 600, 600]}]})
    provider._call_api = call_api

    regions = asyncio.run(provider.recognize(screenshot_png()))
    assert Image.open(io.BytesIO(sent[0])).format == "JPEG"
    assert regions[0].rect["left"] == 960 and regions[0].rect["top"] == 540  # 0-1000 box on the 1920x1080 capture
