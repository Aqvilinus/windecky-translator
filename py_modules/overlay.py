"""The translation overlay's image (PIL): the captured frame as a still, each translation on a label over its OCR
box (Google Lens style), the status pill while a translation runs. No OS calls: windows/overlay_window.py shows
the image over the game."""
import os

from PIL import Image, ImageDraw, ImageFont, ImageStat

FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
FONT_LATIN = ("segoeui.ttf", "arial.ttf")       # Latin, Cyrillic, Greek
FONT_CJK = ("msyh.ttc", "YuGothM.ttc", "msgothic.ttc")
FONT_HANGUL = ("malgun.ttf", "msyh.ttc")


# ---------------------------------------------------------------- fonts and text layout
_fonts = {}


def _first_font(names):
    return next((p for p in (os.path.join(FONT_DIR, n) for n in names) if os.path.exists(p)), None)


_FONT_FILES = {"latin": _first_font(FONT_LATIN), "cjk": _first_font(FONT_CJK), "hangul": _first_font(FONT_HANGUL)}


def _font_file(text):
    if any(0xAC00 <= ord(c) <= 0xD7AF for c in text):
        return _FONT_FILES["hangul"]
    if any(ord(c) >= 0x2E80 for c in text):
        return _FONT_FILES["cjk"]
    return _FONT_FILES["latin"]


def font_for(text, size):
    path = _font_file(text)
    key = (path, int(size))
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(path, int(size)) if path else ImageFont.load_default(int(size))
    return _fonts[key]


def wrap(text, font, max_width):
    """Lines of text that fit max_width (words; characters for text without spaces, e.g. CJK)."""
    out = []
    for para in text.split("\n"):
        tokens = para.split(" ") if " " in para else list(para)
        sep = " " if " " in para else ""
        cur = ""
        for t in tokens:
            cand = t if not cur else cur + sep + t
            if not cur or font.getlength(cand) <= max_width:
                cur = cand
            else:
                out.append(cur)
                cur = t
        out.append(cur)
    return out


# ---------------------------------------------------------------- drawing
def render(state, target, mon, scale, image=None):
    """The overlay image for the monitor rectangle mon = (left, top, width, height). image: the captured frame
    (PIL, capture pixels).

    The overlay is a still: the captured frame covers the window, the translations sit on it, and a thin red border
    marks it. The game keeps running underneath unseen, so the labels never go stale; the shortcut closes the still
    and shows the live game again."""
    mx, my, mw, mh = mon
    img = Image.new("RGBA", (mw, mh), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ox, oy = target["left"] - mx, target["top"] - my  # capture origin inside the image
    tw, th = target["width"], target["height"]
    regions = state.get("regions") or []
    loading = bool(state.get("loading"))

    if image is not None:
        img.paste(image, (ox, oy))
        d.rectangle((ox, oy, ox + tw - 1, oy + th - 1), outline=(244, 67, 54, 255), width=max(1, int(scale)))

    if regions and not loading:
        _draw_labels(d, regions, ox, oy, tw, state, scale, image)

    if loading and state.get("processingStep"):
        _draw_pill(d, state, ox + int(20 * scale), oy + th - int(20 * scale), scale)
    return img


LINE_SPACING = 1.15
FONT_PER_LINE = 0.95  # font size (em) per pixel of an OCR line box's height
LABEL_ALPHA = 245     # nearly opaque, so the original text doesn't show through
WRAP_SLACK = 1.15     # room lost at line ends when wrapping at word boundaries


def font_size_for(text, width, height, max_size, min_size):
    """The largest font size at which the text fits width x height on 1 to 4 lines, from its width on one line (one
    measurement: the width grows with the size) instead of trying sizes. At most max_size, the original line's size;
    no smaller than min_size (a label that doesn't fit then grows)."""
    em = max(font_for(text, 100).getlength(text) / 100, 1e-3)  # the text's width on one line per pixel of font size
    size = max(min(height / (n * LINE_SPACING), width * n / (em * (1 if n == 1 else WRAP_SLACK))) for n in range(1, 5))
    return int(max(min_size, min(size, max_size)))


def _background(image, box):
    """Median colour of a thin ring around the box in the captured frame (the text's background)."""
    if image is None:
        return None
    x0, y0, x1, y1 = (int(v) for v in box)
    outer = (max(0, x0 - 3), max(0, y0 - 3), min(image.width, x1 + 3), min(image.height, y1 + 3))
    crop = image.crop(outer).convert("RGB")
    ring = Image.new("L", crop.size, 255)
    ring.paste(0, (x0 - outer[0], y0 - outer[1], x1 - outer[0], y1 - outer[1]))  # the box itself is left out
    if not ring.getbbox():  # the box covers the whole frame: no ring
        return None
    return tuple(ImageStat.Stat(crop, ring).median)


def auto_alignments(boxes, scale):
    """Alignment of each box's translation, as the original is laid out: a box that shares its left edge with a box
    stacked next to it (a list of choices) is left-aligned, its right edge right-aligned, anything else centred (its
    box hugs the original text, so the translation stays where the original was)."""
    tol = 8 * scale

    def stacked(a, b):
        return min(abs(a[1] - b[3]), abs(b[1] - a[3])) <= 1.5 * max(a[3] - a[1], b[3] - b[1])

    out = []
    for i, a in enumerate(boxes):
        near = [b for j, b in enumerate(boxes) if j != i and stacked(a, b)]
        out.append("left" if any(abs(a[0] - b[0]) <= tol for b in near)
                   else "right" if any(abs(a[2] - b[2]) <= tol for b in near) else "center")
    return out


def paragraphs(regions, boxes):
    """Paragraph id and line height of each box. Lines stacked within a line's height of each other, overlapping
    horizontally, are one paragraph, and its line height is its tallest line's: a box is only as high as its glyphs,
    so a line without tall letters ("mouse.") has a box about half a line high."""
    own = [(y1 - y0) / max(1, len([t for t in (r.get("text") or "").split("\n") if t.strip()]))
           for r, (x0, y0, x1, y1) in zip(regions, boxes)]
    group = list(range(len(boxes)))
    for i, a in enumerate(boxes):
        for j, b in enumerate(boxes):
            gap = max(b[1] - a[3], a[1] - b[3])
            if group[i] != group[j] and min(a[2], b[2]) > max(a[0], b[0]) and gap <= max(own[i], own[j]):
                old = group[j]
                group = [group[i] if g == old else g for g in group]
    tallest = {}
    for g, h in zip(group, own):
        tallest[g] = max(tallest.get(g, 0), h)
    return group, [tallest[g] for g in group]


def _draw_labels(d, regions, ox, oy, img_width, state, scale, image=None):
    """Google Lens style, the same rules for every label: the translation covers its OCR box on the box's own
    background colour, aligned as the original (auto_alignments), in its paragraph's line size. It may reach a line's
    height past its box into free space (never over another box or past the screen edge). A paragraph's lines share
    one size: the one its longest translation fits in."""
    pad = 2 * scale
    font_scale = float(state.get("fontScale") or 1.0)
    boxes = [tuple((r.get("rect") or {}).get(k, 0) for k in ("left", "top", "right", "bottom")) for r in regions]
    aligns = auto_alignments(boxes, scale)
    group, line_px = paragraphs(regions, boxes)

    def room(i):
        """(text, width, height) label i may take."""
        x0, y0, x1, y1 = boxes[i]
        text = (regions[i].get("translatedText") or regions[i].get("text") or "").strip()
        n_lines = max(1, len([t for t in (regions[i].get("text") or "").split("\n") if t.strip()]))
        left, right = max(pad, x0 - line_px[i]), min(img_width - pad, x1 + line_px[i])
        for u0, v0, u1, v1 in boxes:
            if y0 < v1 and y1 > v0:
                if u0 >= x1:
                    right = min(right, u0 - pad)
                elif u1 <= x0:
                    left = max(left, u1 + pad)
        cx = (x0 + x1) / 2
        space = {"left": right - x0, "right": x1 - left}.get(aligns[i], 2 * min(cx - left, right - cx))
        width = space + 2 * pad - 4 * scale
        height = max(y1 - y0, n_lines * line_px[i]) + 2 * pad
        return text, width, height

    shown = [i for i, (r, b) in enumerate(zip(regions, boxes))
             if (r.get("translatedText") or r.get("text") or "").strip() and b[2] > b[0] and b[3] > b[1]]
    rooms = {i: room(i) for i in shown}
    size = {}
    for i in shown:
        max_size = max(8 * scale, line_px[i] * FONT_PER_LINE * font_scale)
        own = font_size_for(*rooms[i], max_size, max(8 * scale, max_size * 0.55))
        size[group[i]] = min(size.get(group[i], own), own)

    for i in shown:
        (x0, y0, x1, y1), align = boxes[i], aligns[i]
        text, width, height = rooms[i]
        font_size = size[group[i]]
        font = font_for(text, font_size)
        lines = wrap(text, font, width)  # more lines than fit: the label grows downwards
        line_h = font_size * LINE_SPACING
        label_w = max(x1 - x0 + 2 * pad, max(font.getlength(t) for t in lines) + 4 * scale)
        label_h = max(height, len(lines) * line_h)
        cx = (x0 + x1) / 2
        lx = {"left": x0 - pad, "right": x1 + pad - label_w}.get(align, cx - label_w / 2) + ox
        ly = (y0 + y1) / 2 - label_h / 2 + oy  # centred on the box (a short line's box is lower than its text)

        bg = _background(image, (x0, y0, x1, y1)) if image is not None else None
        bg = bg or (0, 0, 0)
        fg = (20, 20, 20, 255) if 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2] > 150 else (255, 255, 255, 255)
        d.rounded_rectangle((lx, ly, lx + label_w, ly + label_h), radius=max(1, int(3 * scale)), fill=bg + (LABEL_ALPHA,))

        ty = ly + (label_h - len(lines) * line_h) / 2
        for t in lines:
            lw = font.getlength(t)
            tx = {"left": lx + 2 * scale, "right": lx + label_w - 2 * scale - lw}.get(align, lx + (label_w - lw) / 2)
            d.text((tx, ty + line_h / 2), t, font=font, fill=fg, anchor="lm")
            ty += line_h


def _draw_pill(d, state, x, bottom, scale):
    step = state.get("processingStep") or ""
    is_error = bool(state.get("processingIsError"))
    detail = "" if is_error else (state.get("processingDetail") or "")
    title = step if is_error else step + "..."
    f1 = font_for(title, 14 * scale)
    f2 = font_for(detail, 10 * scale) if detail else None
    icon = 18 * scale
    text_w = max(f1.getlength(title), f2.getlength(detail) if f2 else 0)
    h = 14 * scale * 1.3 + (10 * scale * 1.3 if f2 else 0) + 16 * scale
    w = 12 * scale + icon + 10 * scale + text_w + 12 * scale
    y = bottom - h
    d.rounded_rectangle((x, y, x + w, bottom), radius=int(h / 2), fill=(0, 0, 0, 178))
    ix, iy = x + 12 * scale, y + (h - icon) / 2
    if is_error:
        d.polygon([(ix + icon / 2, iy), (ix + icon, iy + icon), (ix, iy + icon)], fill=(255, 107, 107, 255))
    else:
        d.arc((ix, iy, ix + icon, iy + icon), 200, 120, fill=(52, 152, 219, 255), width=max(2, int(3 * scale)))
    tx = ix + icon + 10 * scale
    d.text((tx, y + 8 * scale), title, font=f1, fill=(255, 255, 255, 255))
    if f2:
        d.text((tx, y + 8 * scale + 14 * scale * 1.3), detail, font=f2, fill=(255, 255, 255, 178))
