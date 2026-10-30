"""Screenshot of the foreground window with Windows.Graphics.Capture.

Windows hands over the window's composed content, so it works the same for DirectX, Vulkan, OpenGL and plain Win32
apps (borderless and windowed; true exclusive fullscreen is the one case Windows can't capture). Capturing one window
also leaves out anything drawn over it, including our own overlay window. The capture border is switched off where
Windows allows it (it does for desktop apps on Windows 11).

capture_foreground() returns a Capture: PNG bytes (for the OCR engines) and the decoded frame (for the overlay's
still and label colours), plus the window's on-screen rectangle (the frame's top-left corner in screen pixels), which
the overlay uses to put the translations exactly over the captured text.
"""
import asyncio
import ctypes
import io
import logging
import time
from ctypes import wintypes
from dataclasses import dataclass

from winrt.windows.graphics.capture import Direct3D11CaptureFramePool
from winrt.windows.graphics.capture.interop import create_for_window
from winrt.windows.graphics.directx import DirectXPixelFormat
from winrt.windows.graphics.directx.direct3d11.interop import create_direct3d11_device
from winrt.windows.graphics.imaging import BitmapAlphaMode, SoftwareBitmap
from winrt.windows.storage.streams import Buffer

logger = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetAncestor.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
GA_ROOT = 2
DWMWA_EXTENDED_FRAME_BOUNDS = 9

_device = None


@dataclass
class Capture:
    png: bytes
    image: object  # PIL.Image, RGB
    width: int
    height: int
    left: int  # screen position of the frame's top-left pixel
    top: int
    hwnd: int


def _frame_bounds(hwnd):
    """The window's visible bounds on screen, which is what Windows.Graphics.Capture captures."""
    r = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r))
    return r.left, r.top


def foreground_window(exclude=()):
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return 0
    hwnd = user32.GetAncestor(hwnd, GA_ROOT) or hwnd
    return 0 if hwnd in exclude else int(hwnd)


async def capture_window(hwnd, timeout=1.0):
    """One frame of the window as a SoftwareBitmap (BGRA8, premultiplied). The D3D device is made once; if it was lost
    (GPU reset, driver update, sometimes after sleep) the capture fails, and a new device is made for a second try."""
    global _device
    try:
        return await _capture_window(hwnd, timeout)
    except TimeoutError:
        raise
    except Exception as e:  # noqa: BLE001 - any WinRT failure: retry once on a fresh device
        logger.warning("capture failed (%r), retrying with a new D3D device", e)
        _device = None
        return await _capture_window(hwnd, timeout)


async def _capture_window(hwnd, timeout):
    global _device
    if _device is None:
        _device = create_direct3d11_device()
    item = create_for_window(hwnd)
    size = item.size
    pool = Direct3D11CaptureFramePool.create_free_threaded(_device, DirectXPixelFormat.B8_G8_R8_A8_UINT_NORMALIZED, 1, size)
    session = pool.create_capture_session(item)
    try:
        try:
            session.is_border_required = False
        except Exception:  # noqa: BLE001 - older builds: the yellow border shows briefly
            pass
        try:
            session.is_cursor_capture_enabled = False
        except Exception:  # noqa: BLE001
            pass
        session.start_capture()
        deadline = time.monotonic() + timeout
        frame = None
        while frame is None and time.monotonic() < deadline:
            frame = pool.try_get_next_frame()
            if frame is None:
                await asyncio.sleep(0.01)
        if frame is None:
            raise TimeoutError("no frame from Windows.Graphics.Capture")
        try:
            return await SoftwareBitmap.create_copy_from_surface_async(frame.surface, BitmapAlphaMode.PREMULTIPLIED)
        finally:
            frame.close()
    finally:
        session.close()
        pool.close()


def bitmap_to_png(bmp):
    """(PNG bytes, PIL RGB image) of the frame."""
    from PIL import Image
    w, h = bmp.pixel_width, bmp.pixel_height
    buf = Buffer(w * h * 4)
    bmp.copy_to_buffer(buf)
    img = Image.frombuffer("RGBA", (w, h), memoryview(buf), "raw", "BGRA", 0, 1).convert("RGB")
    out = io.BytesIO()
    img.save(out, "PNG", compress_level=1)
    return out.getvalue(), img


async def capture_foreground(exclude=()):
    """Capture the foreground window; None if there is none (or it is excluded, e.g. our own overlay)."""
    hwnd = foreground_window(exclude)
    if not hwnd:
        return None
    t0 = time.perf_counter()
    bmp = await capture_window(hwnd)
    left, top = _frame_bounds(hwnd)
    png, image = await asyncio.to_thread(bitmap_to_png, bmp)  # 15-120 ms for a full-screen frame: off the event loop
    logger.info("captured window %#x %dx%d at (%d,%d) in %.0f ms", hwnd, bmp.pixel_width, bmp.pixel_height, left, top,
                (time.perf_counter() - t0) * 1000)
    return Capture(png, image, bmp.pixel_width, bmp.pixel_height, left, top, hwnd)
