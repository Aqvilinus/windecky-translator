"""main.py's Plugin driven through the calls the frontend makes, end to end inside the backend: settings, capture,
OCR, translation (Google, the Bing fallback, the cache), the overlay window's drawing, the game pause and the
hotkey. Only the Windows and network edges are emulated (harness.py)."""
import json
import os
import threading

import pytest
from PIL import ImageChops

import harness



def overlay_state(regions, **kw):
    """What src/windows.ts sends for a shown translation."""
    return {"visible": True, "regions": regions, "loading": False, "processingStep": "", "processingDetail": "",
            "processingIsError": False, "fontScale": 1.0, **kw}


def pixels(img):
    return list(img.get_flattened_data())


def translate_screen(backend):
    shot = backend.call("take_screenshot", "The Banner Saga")
    regions = backend.call("recognize_text_file", shot["path"])
    return shot, regions, backend.call("translate_text", regions, "en", "auto")


# ---------------------------------------------------------------- start and settings
def test_start_on_windows(backend, windows):
    assert windows.processes.log[0] == "resume_leftovers"  # a game an earlier run paused is resumed first
    assert windows.hotkey.enabled is True
    s = backend.call("get_all_settings")
    assert s["ocr_provider"] == "ocrspace" and s["translation_provider"] == "freegoogle" and s["enabled"] is True
    status = backend.call("get_provider_status")
    assert status["ocr_provider"] == "OCR.space" and status["translation_available"] is True


def test_settings_persist_across_a_restart(start, windows):
    b = start()
    assert b.call("set_setting", "target_language", "ru") is True
    assert b.call("set_setting", "font_scale", 1.3) is True
    assert b.call("set_setting", "enabled", False) is True
    assert windows.hotkey.enabled is False  # the shortcut goes off with the plugin

    b = start()
    s = b.call("get_all_settings")
    assert (s["target_language"], s["font_scale"], s["enabled"]) == ("ru", 1.3, False)
    assert windows.hotkey.enabled is False


def test_api_keys_never_reach_the_frontend(backend):
    key = "AIzaSyD-test-key-0123456789abcdef"
    assert backend.call("set_setting", "google_api_key", f" {key}​") is True  # pasted with junk around it
    shown = backend.call("get_all_settings")["google_api_key"]
    assert key not in json.dumps(backend.call("get_all_settings")) and shown == "AIz…cdef"
    # saving the masked key back (a dialog closed unchanged) keeps the real one
    assert backend.call("set_setting", "google_api_key", shown) is True
    with open(backend.plugin._settings.settings_path, encoding="utf-8") as f:
        assert json.load(f)["google_api_key"] == key


def test_a_damaged_settings_file_is_kept_aside(start, tmp_path):
    settings = tmp_path / "settings"
    settings.mkdir()
    (settings / "decky-translator-settings.json").write_text('{"target_language": "de", "ena', encoding="utf-8")
    b = start(write_settings=False)
    assert (settings / "decky-translator-settings.json.damaged").exists()
    assert b.call("get_all_settings")["target_language"] == "en"


# ---------------------------------------------------------------- the translation pipeline
def test_capture_ocr_translate_overlay(backend, windows, net):
    shot, regions, translated = translate_screen(backend)

    # the capture stays in memory: the frontend gets only a name
    assert shot == {"path": shot["path"]} and shot["path"].endswith(".png") and "The Banner Saga" in shot["path"]
    assert windows.captures == 1 and not os.path.exists(shot["path"])
    assert [r["text"] for r in regions] == [t for t, _ in harness.SCREEN]
    for r, (_, (x, y)) in zip(regions, harness.SCREEN):
        assert abs(r["rect"]["left"] - x) <= 4 and abs(r["rect"]["top"] - y) <= 12
    sent = net.calls(harness.OCRSPACE_URL)[0][3]
    assert sent["base64Image"].startswith("data:image/png;base64,")  # the captured PNG went to OCR

    assert [r["translatedText"] for r in translated] == ["Welcome, traveller", "New game"]
    assert len(net.calls(harness.GOOGLE_URL)) == 1  # one request for all lines
    assert net.calls(harness.BING_URL) == []

    assert backend.call("native_overlay_update", overlay_state(translated)) is True
    overlay = windows.overlay
    state, target = overlay.shown[-1]
    assert overlay.visible and target["hwnd"] == harness.GAME_HWND and state["regions"] == translated

    assert backend.call("native_overlay_update", {"visible": False}) is True
    assert not overlay.visible


def test_overlay_draws_the_labels_over_the_text(backend, windows, net):
    _, _, translated = translate_screen(backend)
    backend.call("native_overlay_update", overlay_state(translated))
    shot = windows.capture_image.convert("RGBA")
    drawn = windows.overlay.image()
    assert drawn.size == shot.size

    diff = ImageChops.difference(drawn, shot).convert("L")
    for r in translated:  # each original line is covered by its label
        box = (r["rect"]["left"], r["rect"]["top"], r["rect"]["right"], r["rect"]["bottom"])
        region = diff.crop(box)
        changed = sum(1 for p in pixels(region) if p > 40)
        assert changed > 0.1 * region.width * region.height, r["text"]
    # nothing drawn far from the text: the lower half is the captured frame (but for the 1 px border)
    lower = diff.crop((10, 220, shot.width - 10, shot.height - 10))
    assert max(pixels(lower)) < 10


def test_google_rate_limit_falls_back_to_bing(backend, net):
    net.google_status = 429
    _, regions, translated = translate_screen(backend)
    assert [r["translatedText"] for r in translated] == ["Welcome, traveller", "New game"]
    assert len(net.calls(harness.BING_URL)) == 1
    # Google stays paused for a while: the next translation goes to Bing directly
    net.dictionary["Neues Spiel"] = "New game!"
    backend.call("translate_text", [{**regions[1], "text": "Neues Spiel"}], "en", "auto")
    assert len(net.calls(harness.GOOGLE_URL)) == 1


def test_a_translation_that_gives_nothing_back_is_an_error(backend, net, monkeypatch):
    """Google refuses and Bing's answer is unusable: say so instead of showing the originals as if translated."""
    net.google_status = 429
    free = backend.plugin._provider_manager.get_translation_provider()

    async def unusable(texts, src, tgt):
        return [None] * len(texts)
    monkeypatch.setattr(free._bing, "translate_lines", unusable)
    shot = backend.call("take_screenshot", "Game")
    regions = backend.call("recognize_text_file", shot["path"])
    reply = backend.call("translate_text", regions, "en", "auto")
    assert reply["error"] == "translation_failed" and "did not answer" in reply["message"]
    assert backend.call("get_translation_cache_stats")["entries"] == 0


def test_offline_translation_failures_are_errors(backend, monkeypatch):
    from providers import TranslationError
    from providers.ct2_translate import CT2TranslateProvider
    provider = CT2TranslateProvider.__new__(CT2TranslateProvider)  # no worker, no model folder
    with pytest.raises(TranslationError, match="source language"):
        provider._translate_batch_sync(["Hallo"], "auto", "en")


def test_a_broken_cache_does_not_stop_the_translation(backend, net, monkeypatch):
    import sqlite3

    def locked(*args):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(backend.plugin._translation_cache, "get_many", locked)
    monkeypatch.setattr(backend.plugin._translation_cache, "put_many", locked)
    _, _, translated = translate_screen(backend)
    assert [r["translatedText"] for r in translated] == ["Welcome, traveller", "New game"]


def test_translation_cache(start, net):
    b = start()
    _, regions, first = translate_screen(b)
    assert b.call("translate_text", regions, "en", "auto") == first
    assert len(net.calls(harness.GOOGLE_URL)) == 1  # the second came from the cache
    assert b.call("get_translation_cache_stats")["entries"] == 2
    assert b.call("clear_translation_cache") is not None
    b.call("translate_text", regions, "en", "auto")
    assert len(net.calls(harness.GOOGLE_URL)) == 2

    b = start({"translation_cache_enabled": False}, fresh=True)
    b.call("translate_text", regions, "en", "auto")
    b.call("translate_text", regions, "en", "auto")
    assert len(net.calls(harness.GOOGLE_URL)) == 4


def test_no_network(backend, net):
    net.down |= {harness.GOOGLE_URL, harness.OCRSPACE_URL}
    shot = backend.call("take_screenshot", "Game")
    assert backend.call("recognize_text_file", shot["path"]) == {"error": "network_error", "message": "No internet connection"}
    regions = [{"text": "Hallo Welt", "rect": {"left": 0, "top": 0, "right": 10, "bottom": 10}, "confidence": 1, "isDialog": False}]
    assert backend.call("translate_text", regions, "en", "auto") == {"error": "network_error", "message": "No internet connection"}


def test_ocr_engine_failures_reach_the_frontend(backend, monkeypatch):
    """A failing engine is reported with its reason, not as an empty result ("No text found")."""
    from providers import OCRError
    provider = backend.plugin._provider_manager.get_ocr_provider()

    async def times_out(image, language="auto"):
        raise OCRError("On-device OCR timed out after 120 s")
    monkeypatch.setattr(provider, "recognize", times_out)
    shot = backend.call("take_screenshot", "Game")
    assert backend.call("recognize_text_file", shot["path"]) == {
        "error": "ocr_failed", "message": "On-device OCR timed out after 120 s"}

    async def crashes(image, language="auto"):
        raise ValueError("bug")
    monkeypatch.setattr(provider, "recognize", crashes)
    shot = backend.call("take_screenshot", "Game")
    assert backend.call("recognize_text_file", shot["path"])["error"] == "ocr_failed"


def test_chrome_screen_ai_failures_raise(monkeypatch, tmp_path):
    """The engine's own failures (crash, timeout, unreadable output) become OCRError with a reason."""
    import subprocess
    from providers import OCRError
    from providers.chromescreenai_provider import ChromeScreenAIProvider
    provider = ChromeScreenAIProvider(model_dir=str(tmp_path))
    provider._python_path = "python.exe"

    def run(result=None, error=None):
        def fake(*args, **kwargs):
            if error:
                raise error
            return result
        monkeypatch.setattr(subprocess, "run", fake)

    for result, error, reason in (
        (subprocess.CompletedProcess([], 3, "", "access violation"), None, "exit code 3"),
        (subprocess.CompletedProcess([], 0, "not json", ""), None, "unreadable"),
        (subprocess.CompletedProcess([], 0, '{"error": "model failed to load"}', ""), None, "model failed to load"),
        (None, subprocess.TimeoutExpired("python.exe", 120), "timed out"),
    ):
        run(result, error)
        with pytest.raises(OCRError, match=reason):
            provider._recognize_oneshot(b"png")


def test_nothing_captured(backend, windows):
    windows.capture_image = None  # no foreground window
    assert backend.call("take_screenshot", "Game") == {"path": ""}


def test_screenshot_files_outside_the_plugin_are_refused(backend, tmp_path):
    other = tmp_path / "secret.png"
    other.write_bytes(b"not mine")
    assert backend.call("recognize_text_file", str(other)) == []
    assert backend.call("discard_screenshot", str(other)) is False
    assert other.exists()


# ---------------------------------------------------------------- Windows: pause, hotkey, Steam apps
def test_pause_game_while_translating(start, windows, net):
    b = start({"pause_game_on_overlay": True})
    _, _, translated = translate_screen(b)
    b.call("native_overlay_update", overlay_state(translated))
    assert windows.processes.suspended == {harness.GAME_PID}
    b.call("native_overlay_update", overlay_state(translated, fontScale=1.2))  # an update: no second pause
    assert windows.processes.log.count(("suspend", harness.GAME_PID)) == 1
    b.call("native_overlay_update", {"visible": False})
    assert windows.processes.suspended == set()


def test_a_game_that_cannot_be_paused_is_reported_once(start, windows, net, main):
    b = start({"pause_game_on_overlay": True})
    _, _, translated = translate_screen(b)
    windows.processes.suspend = lambda pid: False  # e.g. access denied

    async def show_twice():
        for _ in range(2):
            b.plugin._overlay_visible = False
            await b.plugin.native_overlay_update(overlay_state(translated))
        await harness.asyncio.sleep(0.05)
    b.run(show_twice())
    assert [e for e in main.test_events if e[0] == "translator_problem"] == [
        ("translator_problem", ("Pause Game While Translating: Windows didn't let the plugin pause this game "
                                "(details in the plugin log)",))]


def test_switching_the_plugin_off_resumes_a_paused_game(start, windows, net):
    b = start({"pause_game_on_overlay": True})
    _, _, translated = translate_screen(b)
    b.call("native_overlay_update", overlay_state(translated))
    b.call("set_setting", "enabled", False)
    assert windows.processes.suspended == set()


def test_a_taken_hotkey_is_reported(backend):
    assert backend.call("get_boot_status") == []
    backend.plugin._hotkey.error = 1409
    [problem] = backend.call("get_boot_status")
    assert "Ctrl+Alt+T is taken by another program" in problem


def test_overlay_failures_reach_the_frontend(backend, windows, main):
    backend.call("native_overlay_update", {"visible": False})  # creates the overlay
    windows.overlay.on_error("draw failed: MemoryError()")

    async def wait():
        for _ in range(50):
            if main.test_events:
                return
            await harness.asyncio.sleep(0.01)
    backend.run(wait())
    assert main.test_events == [("translator_problem", ("The translation overlay doesn't work: draw failed: MemoryError()",))]


def test_hotkey_resumes_a_paused_game_even_without_the_frontend(start, windows, net):
    b = start({"pause_game_on_overlay": True})
    _, _, translated = translate_screen(b)
    b.call("native_overlay_update", overlay_state(translated))
    assert windows.processes.suspended == {harness.GAME_PID}

    async def press():  # no frontend answers the event
        t = threading.Thread(target=b.plugin._on_hotkey)  # the hotkey's own thread
        t.start()
        t.join()
        await harness.asyncio.sleep(0.05)

    b.run(press())
    assert windows.processes.suspended == set()


def test_hotkey_reaches_the_frontend(backend, main):
    async def press():
        t = threading.Thread(target=backend.plugin._on_hotkey)  # the hotkey's own thread
        t.start()
        t.join()
        for _ in range(50):
            if main.test_events:
                return
            await harness.asyncio.sleep(0.01)

    backend.run(press())
    assert main.test_events == [("translator_hotkey", ())]


# ---------------------------------------------------------------- the real Windows OCR, where the runner has it
def test_windows_ocr_reads_the_screen(start, windows):
    from providers.windows_ocr import WindowsOCRProvider
    try:
        languages = WindowsOCRProvider().get_supported_languages()
    except Exception as e:  # noqa: BLE001 - no WinRT OCR on this machine
        pytest.skip(f"Windows OCR unavailable: {e!r}")
    if not {"en", "de"} & set(languages):
        pytest.skip(f"no English or German Windows OCR language pack ({languages})")
    b = start({"ocr_provider": "windows_ocr"})
    shot = b.call("take_screenshot", "Game")
    texts = " ".join(r["text"] for r in b.call("recognize_text_file", shot["path"]))
    assert "Willkommen" in texts and "Spiel" in texts
