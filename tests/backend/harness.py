"""main.py without Decky Loader, Steam or a game: what the backend tests run it with.

- Decky's module (decky / decky_plugin) is a stand-in with the directories in a temporary folder, a logger, and
  emit() recording the events sent to the frontend.
- The Windows parts behind main.py's own names are replaced: the capture returns a test image of a game screen, the
  overlay window records what it is told and draws it with the real winport.overlay.render (Pillow) into an image,
  the hotkey and the process pause record their calls.
- HTTP goes through `responses` (requests): Google Translate, Bing and OCR.space answer from the stubs below; any
  other request fails like a dead network, so no test can reach a real service.
"""
import asyncio
import importlib
import json
import logging
import os
import socket
import sys
import types
from urllib.parse import parse_qs

import responses

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GAME_HWND = 0x1234
GAME_PID = 4321

# The emulated game screen: German text, translated to English by the stubbed services
SCREEN = [("Willkommen, Reisender", (40, 40)), ("Neues Spiel", (40, 120))]
DICTIONARY = {"Willkommen, Reisender": "Welcome, traveller", "Neues Spiel": "New game"}


# ---------------------------------------------------------------- Decky
def install_decky(base_dir):
    """Decky's module as main.py sees it (decky.pyi); returns the list emit() appends (event, args) to."""
    dirs = {name: os.path.join(base_dir, name) for name in ("settings", "runtime", "logs", "plugin", "home")}
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)
    events = []

    async def emit(event, *args):
        events.append((event, args))

    mod = types.ModuleType("decky")
    mod.DECKY_PLUGIN_SETTINGS_DIR = dirs["settings"]
    mod.DECKY_PLUGIN_RUNTIME_DIR = dirs["runtime"]
    mod.DECKY_PLUGIN_LOG_DIR = dirs["logs"]
    mod.DECKY_PLUGIN_DIR = ROOT
    mod.DECKY_HOME = dirs["home"]
    mod.DECKY_USER_HOME = dirs["home"]
    mod.HOME = dirs["home"]
    mod.DECKY_VERSION = "v3.3.1-test"
    mod.DECKY_PLUGIN_NAME = "WinDecky Translator"
    mod.DECKY_PLUGIN_VERSION = "test"
    mod.logger = logging.getLogger("decky-translator-test")
    mod.emit = emit
    sys.modules["decky"] = mod
    sys.modules["decky_plugin"] = mod
    os.environ.update(DECKY_PLUGIN_SETTINGS_DIR=dirs["settings"], DECKY_PLUGIN_LOG_DIR=dirs["logs"],
                      DECKY_PLUGIN_DIR=ROOT, DECKY_HOME=dirs["home"], TEMP=dirs["runtime"])
    return mod, events


def import_main():
    """Import main.py once (it sets up logging and paths at import)."""
    if "main" in sys.modules:
        return sys.modules["main"]
    return importlib.import_module("main")


# ---------------------------------------------------------------- the game screen
def font(size=28):
    from winport.overlay import font_for
    return font_for("Willkommen", size)


def word_boxes():
    """OCR.space-style words with pixel boxes of SCREEN as drawn by screen_image()."""
    f = font()
    lines = []
    for text, (x, y) in SCREEN:
        words, cx = [], x
        for w in text.split(" "):
            left, top, right, bottom = f.getbbox(w)
            words.append({"WordText": w, "Left": cx + left, "Top": y + top, "Width": right - left, "Height": bottom - top})
            cx += f.getlength(w + " ")
        lines.append({"LineText": text, "Words": words})
    return lines


def screen_image(width=640, height=360):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (width, height), (24, 32, 48))
    d = ImageDraw.Draw(img)
    for text, pos in SCREEN:
        d.text(pos, text, font=font(), fill=(235, 235, 235))
    return img


def capture_of(img, left=100, top=50):
    import io
    from winport.capture import Capture
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return Capture(png=buf.getvalue(), image=img, width=img.width, height=img.height, left=left, top=top, hwnd=GAME_HWND)


# ---------------------------------------------------------------- Windows parts
class FakeOverlay:
    """winport.overlay.Overlay: records show/hide and draws each shown state with the real render()."""
    instances = []

    def __init__(self):
        self.shown = []        # (state, target) per show()
        self.hides = 0
        self.visible = False
        self.hwnd = None
        type(self).instances.append(self)

    def show(self, state, target):
        self.shown.append((state, target))
        self.visible = True

    def hide(self):
        self.hides += 1
        self.visible = False

    def stop(self):
        self.visible = False

    def image(self, index=-1, scale=1.0):
        """What the overlay window would show for the index'th show(), on a monitor the size of the capture."""
        from winport.overlay import render
        state, target = self.shown[index]
        tgt = dict(target)
        mon = (tgt["left"], tgt["top"], tgt["width"], tgt["height"])
        return render(state, tgt, mon, scale, tgt.get("image"))


class FakeHotkey:
    def __init__(self, on_press):
        self.on_press = on_press
        self.enabled = None
        self.holds = []
        self.refreshes = 0
        self.closed = False

    def set_enabled(self, on):
        self.enabled = on

    def hold(self, on, reason="pause"):
        self.holds.append((on, reason))

    def refresh(self):
        self.refreshes += 1

    def status(self):
        return {"registered": bool(self.enabled), "hotkey": "Ctrl+Alt+T"}

    def close(self):
        self.closed = True


class FakeProcesses:
    """winport.process: the game's pause (NtSuspendProcess) recorded instead of done."""

    def __init__(self):
        self.suspended = set()
        self.log = []

    def resume_leftovers(self):
        self.log.append("resume_leftovers")

    def game_pid(self, hwnd):
        return GAME_PID if hwnd == GAME_HWND else 0

    def suspend(self, pid):
        self.log.append(("suspend", pid))
        self.suspended.add(pid)
        return True

    def any_suspended(self):
        return bool(self.suspended)

    def resume_all(self):
        self.log.append("resume_all")
        self.suspended.clear()


class FakeWindows:
    """The Windows seams of main.py, installed with install(main) and taken out with restore()."""

    def __init__(self):
        self.capture_image = screen_image()
        self.captures = 0
        self.overlay_cls = type("Overlay", (FakeOverlay,), {"instances": []})
        self.processes = FakeProcesses()
        self.hotkeys = []
        self._saved = {}

    @property
    def overlay(self):
        return self.overlay_cls.instances[-1] if self.overlay_cls.instances else None

    @property
    def hotkey(self):
        return self.hotkeys[-1] if self.hotkeys else None

    async def capture_foreground(self, exclude=()):
        self.captures += 1
        return capture_of(self.capture_image) if self.capture_image is not None else None

    def _make_hotkey(self, on_press):
        hk = FakeHotkey(on_press)
        self.hotkeys.append(hk)
        return hk

    def install(self, main):
        seams = {"capture_foreground": self.capture_foreground, "Overlay": self.overlay_cls,
                 "GameHotkey": self._make_hotkey, "winprocess": self.processes}
        for name, value in seams.items():
            self._saved[name] = getattr(main, name)
            setattr(main, name, value)
        return self

    def restore(self, main):
        for name, value in self._saved.items():
            setattr(main, name, value)


# ---------------------------------------------------------------- the network
GOOGLE_URL = "https://translate.googleapis.com/translate_a/single"
BING_PAGE = "https://www.bing.com/translator"
BING_URL = "https://www.bing.com/ttranslatev3"
OCRSPACE_URL = "https://api.ocr.space/parse/image"
BING_PAGE_HTML = ('<html><script>_G={IG:"0123456789ABCDEF"};params_AbusePreventionHelper = [1700000000000,"tok123",3600000];'
                  '</script><div data-iid="translator.5023"></div></html>')


def translate_lines(text, dictionary=DICTIONARY):
    return "\n".join(dictionary.get(line, line) for line in text.split("\n"))


class Network:
    """responses.RequestsMock with the services' stubs; counts the calls per service."""

    def __init__(self):
        self.mock = responses.RequestsMock(assert_all_requests_are_fired=False)
        self.dictionary = dict(DICTIONARY)
        self.google_status = 200
        self.ocr_lines = word_boxes()
        self.languages = ("auto", "en")  # (source, target) the translators expect; others are refused

    def __enter__(self):
        self.mock.__enter__()
        self.mock.add_callback(responses.POST, GOOGLE_URL, callback=self._google)
        self.mock.add_callback(responses.GET, GOOGLE_URL, callback=lambda r: (200, {}, "[[[\"ok\",\"ok\"]]]"))
        self.mock.add(responses.GET, BING_PAGE, body=BING_PAGE_HTML)
        self.mock.add_callback(responses.POST, BING_URL, callback=self._bing)
        self.mock.add_callback(responses.POST, OCRSPACE_URL, callback=self._ocrspace)
        self.mock.add(responses.HEAD, OCRSPACE_URL, status=200)
        return self

    def __exit__(self, *exc):
        return self.mock.__exit__(*exc)

    def calls(self, url):
        return [c for c in self.mock.calls if c.request.url.split("?")[0] == url]

    def _google(self, request):
        if self.google_status != 200:
            return self.google_status, {}, "Too Many Requests"
        query = parse_qs(request.url.split("?", 1)[1])
        if (query["sl"][0], query["tl"][0]) != self.languages:
            return 400, {}, f"unexpected languages {query['sl'][0]} -> {query['tl'][0]}"
        text = parse_qs(request.body)["q"][0]
        return 200, {}, json.dumps([[[translate_lines(text, self.dictionary), text, None, None]], None, "de"])

    def _bing(self, request):
        form = parse_qs(request.body)
        assert form["token"] == ["tok123"] and form["key"] == ["1700000000000"], form
        src, tgt = self.languages
        if (form["fromLang"][0], form["to"][0]) != ("auto-detect" if src == "auto" else src, tgt):
            return 400, {}, json.dumps({"statusCode": 400})
        out = translate_lines(form["text"][0], self.dictionary)
        return 200, {}, json.dumps([{"detectedLanguage": {"language": "de"}, "translations": [{"text": out, "to": "en"}]}])

    def _ocrspace(self, request):
        return 200, {}, json.dumps({"ParsedResults": [{"FileParseExitCode": 1, "TextOverlay": {"Lines": self.ocr_lines},
                                                       "ParsedText": "\n".join(l["LineText"] for l in self.ocr_lines)}],
                                    "OCRExitCode": 1, "IsErroredOnProcessing": False})


def block_sockets():
    """Anything that bypasses requests (urllib, a websocket) must not reach the internet either."""
    real_connect = socket.socket.connect

    def connect(sock, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise OSError(f"tests must not use the network (connect to {address})")
        return real_connect(sock, address)

    socket.socket.connect = connect
    return lambda: setattr(socket.socket, "connect", real_connect)


# ---------------------------------------------------------------- a running plugin
class Backend:
    """A started Plugin on an event loop of its own; call() runs a frontend call to completion."""

    def __init__(self, main, settings_dir, settings=None):
        self.main = main
        self.settings_dir = settings_dir
        os.makedirs(settings_dir, exist_ok=True)
        if settings:
            with open(os.path.join(settings_dir, "decky-translator-settings.json"), "w", encoding="utf-8") as f:
                json.dump(settings, f)
        self.loop = asyncio.new_event_loop()
        self.plugin = None

    def start(self):
        self.main.settingsDir = self.settings_dir
        self.plugin = self.main.Plugin()
        self.plugin._screenshotPath = os.path.join(self.settings_dir, "screenshots")
        self.loop.run_until_complete(self.plugin._main())
        return self

    def call(self, method, *args):
        return self.loop.run_until_complete(getattr(self.plugin, method)(*args))

    def run(self, coro):
        return self.loop.run_until_complete(coro)

    def stop(self):
        """_unload without closing main.py's log files (they belong to the module, which stays imported)."""
        p = self.plugin
        if p:
            self.main.winprocess.resume_all()
            if p._provider_manager:
                p._provider_manager.shutdown()
            if p._translation_cache:
                p._translation_cache.close()
            if p._overlay:
                p._overlay.stop()
        self.loop.close()
