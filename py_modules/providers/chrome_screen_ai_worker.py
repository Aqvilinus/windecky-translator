#!/usr/bin/env python3
"""The Chrome Screen AI worker (providers/chrome_screen_ai.py starts it): loads chrome_screen_ai.dll with ctypes and
answers JSON lines on stdin with JSON lines on stdout."""

import ctypes
import json
import os
import sys
import traceback

_SK_COLOR_TYPE_RGBA_8888 = 4
_SK_ALPHA_TYPE_OPAQUE = 1

# Skia structs PerformOCR reads. Only populated fields matter.
class _SkColorInfo(ctypes.Structure):
    _fields_ = [
        ('fColorSpace', ctypes.c_void_p),
        ('fColorType', ctypes.c_int32),
        ('fAlphaType', ctypes.c_int32),
    ]


class _SkISize(ctypes.Structure):
    _fields_ = [
        ('fWidth', ctypes.c_int32),
        ('fHeight', ctypes.c_int32),
    ]


class _SkImageInfo(ctypes.Structure):
    _fields_ = [
        ('fColorInfo', _SkColorInfo),
        ('fDimensions', _SkISize),
    ]


class _SkPixmap(ctypes.Structure):
    _fields_ = [
        ('fPixels', ctypes.c_void_p),
        ('fRowBytes', ctypes.c_size_t),
        ('fInfo', _SkImageInfo),
    ]


class _SkBitmap(ctypes.Structure):
    _fields_ = [
        ('fPixelRef', ctypes.c_void_p),
        ('fPixmap', _SkPixmap),
        ('fFlags', ctypes.c_uint32),
    ]


# Callback signatures for SetFileContentFunctions.
_SizeCb = ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.c_char_p)
_ContentCb = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_void_p)


class ScreenAIEngine:
    """Wraps chrome_screen_ai.dll and PerformOCR."""

    def __init__(self, model_dir):
        self.model_dir = model_dir

        # Anchor CFUNCTYPE refs on self; GC would dangle the C callbacks.
        @_SizeCb
        def get_size(p):
            try:
                full = os.path.join(self.model_dir, p.decode('utf-8'))
                return os.path.getsize(full) if os.path.exists(full) else 0
            except Exception:
                return 0

        @_ContentCb
        def get_content(p, n, out_ptr):
            try:
                full = os.path.join(self.model_dir, p.decode('utf-8'))
                if not os.path.exists(full):
                    return
                with open(full, 'rb') as f:
                    data = f.read(n)
                ctypes.memmove(out_ptr, data, len(data))
            except Exception:
                pass

        self._size_cb = get_size
        self._content_cb = get_content

        os.add_dll_directory(self.model_dir)  # its own dependencies sit next to it
        self.lib = ctypes.CDLL(os.path.join(self.model_dir, 'chrome_screen_ai.dll'))

        self.lib.SetFileContentFunctions.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.lib.SetFileContentFunctions.restype = None
        self.lib.InitOCRUsingCallback.restype = ctypes.c_bool
        self.lib.SetOCRLightMode.argtypes = [ctypes.c_bool]
        self.lib.SetOCRLightMode.restype = None
        self.lib.PerformOCR.argtypes = [
            ctypes.POINTER(_SkBitmap), ctypes.POINTER(ctypes.c_uint32)
        ]
        self.lib.PerformOCR.restype = ctypes.c_void_p
        self.lib.FreeLibraryAllocatedCharArray.argtypes = [ctypes.c_void_p]
        self.lib.FreeLibraryAllocatedCharArray.restype = None
        self.lib.GetMaxImageDimension.restype = ctypes.c_uint32

        self.lib.SetFileContentFunctions(
            ctypes.cast(self._size_cb, ctypes.c_void_p),
            ctypes.cast(self._content_cb, ctypes.c_void_p),
        )

        if not self.lib.InitOCRUsingCallback():
            raise RuntimeError("InitOCRUsingCallback returned False")

        # Light mode is the smaller/faster model; we want full quality.
        self.lib.SetOCRLightMode(False)

        self.max_dim = int(self.lib.GetMaxImageDimension()) or 2048

    def perform(self, rgba_bytes, width, height):
        bitmap = _SkBitmap()
        # Anchor the buffer on self so it isn't GCed during PerformOCR.
        self._buffer_bytes = rgba_bytes
        self._buffer = ctypes.c_char_p(rgba_bytes)
        bitmap.fPixmap.fPixels = ctypes.cast(self._buffer, ctypes.c_void_p)
        bitmap.fPixmap.fRowBytes = width * 4
        bitmap.fPixmap.fInfo.fColorInfo.fColorType = _SK_COLOR_TYPE_RGBA_8888
        bitmap.fPixmap.fInfo.fColorInfo.fAlphaType = _SK_ALPHA_TYPE_OPAQUE
        bitmap.fPixmap.fInfo.fDimensions.fWidth = width
        bitmap.fPixmap.fInfo.fDimensions.fHeight = height

        out_len = ctypes.c_uint32(0)
        ptr = self.lib.PerformOCR(ctypes.byref(bitmap), ctypes.byref(out_len))
        if not ptr:
            return None
        try:
            data = ctypes.string_at(ptr, out_len.value)
        finally:
            self.lib.FreeLibraryAllocatedCharArray(ptr)
        return data


def _load_image_rgba(image_path, max_dim):
    """Returns (rgba, w, h, scale_x, scale_y); scale maps back to original."""
    from PIL import Image

    img = Image.open(image_path)
    orig_w, orig_h = img.size

    if max(orig_w, orig_h) > max_dim:
        factor = min(max_dim / orig_w, max_dim / orig_h)
        new_w = max(1, int(orig_w * factor))
        new_h = max(1, int(orig_h * factor))
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    if img.mode != 'RGBA':
        img = img.convert('RGBA')

    w, h = img.size
    return img.tobytes(), w, h, orig_w / w, orig_h / h


def _proto_to_regions(proto_bytes, scale_x, scale_y):
    # from this script's folder, not the plugin's providers package (that runs in Decky's Python, with aiohttp)
    from chrome_screen_ai_pb2 import VisualAnnotation

    ann = VisualAnnotation()
    ann.ParseFromString(proto_bytes)

    regions = []
    for line in ann.lines:
        text = (line.utf8_string or "").strip()
        if not text:
            continue
        confidence = float(line.confidence) if line.confidence else None  # in [0,1]; 0 when the engine gives none

        # Treat the proto's rotated rect as axis-aligned; good enough for the overlay.
        bb = line.bounding_box
        x, y, w, h = bb.x, bb.y, bb.width, bb.height
        left = int(round(x * scale_x))
        top = int(round(y * scale_y))
        right = int(round((x + w) * scale_x))
        bottom = int(round((y + h) * scale_y))

        regions.append({
            "text": text,
            "rect": {"left": left, "top": top, "right": right, "bottom": bottom},
            "confidence": confidence,
        })
    return regions


def _write_line(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main():
    """Long-lived worker: one JSON request per line on stdin, one JSON reply per line on stdout.

      >>> {"type":"init","model_dir":"..."}
      <<< {"type":"ready","error":null}

      >>> {"type":"recognize","image_path":"/tmp/x.png"}
      <<< {"type":"result","error":null,"regions":[...]}

      >>> {"type":"shutdown"}
    """
    engine = None
    for line in sys.stdin:
        msg = json.loads(line)
        mtype = msg["type"]

        if mtype == "init":
            try:
                engine = ScreenAIEngine(msg["model_dir"])
                _write_line({"type": "ready", "error": None})
            except Exception as e:
                _write_line({"type": "ready", "error": f"{e}\n{traceback.format_exc()}"})

        elif mtype == "recognize":
            try:
                rgba, w, h, sx, sy = _load_image_rgba(msg["image_path"], engine.max_dim)
                proto = engine.perform(rgba, w, h)
                if proto is None:
                    _write_line({"type": "result", "error": "PerformOCR null", "regions": []})
                else:
                    _write_line({"type": "result", "error": None, "regions": _proto_to_regions(proto, sx, sy)})
            except Exception as e:
                _write_line({"type": "result", "error": str(e), "regions": []})

        elif mtype == "shutdown":
            break

        else:
            _write_line({"type": "result", "error": f"unknown type: {mtype}", "regions": []})


if __name__ == '__main__':
    main()
