"""The real main.py as the backend of the frontend integration tests (pythonBackend.ts): one call per line.

stdin:  {"id": 1, "method": "take_screenshot", "args": ["Game"]}
stdout: {"id": 1, "result": {...}}  or  {"id": 1, "error": "..."}

main.py runs as in tests/backend (harness.py): Decky's module emulated, the Windows parts and the network stubbed.
Two methods are the bridge's own: __restart__ (Decky restarts the backend when it reloads the plugin) and __windows__
(what the emulated overlay window, hotkey and process pause were told).
"""
import json
import os
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
import harness  # noqa: E402

SETTINGS = {"ocr_provider": "ocrspace", "translation_provider": "freegoogle", "target_language": "en"}


def windows_state(windows):
    o = windows.overlay
    return {
        "captures": windows.captures,
        "overlay": None if o is None else {"visible": o.visible, "shows": len(o.shown), "hides": o.hides,
                                           "regions": o.shown[-1][0].get("regions") if o.shown else None},
        "hotkey": None if windows.hotkey is None else {"enabled": windows.hotkey.enabled, "holds": windows.hotkey.holds},
        "suspended": sorted(windows.processes.suspended),
    }


def main():
    out = sys.stdout
    sys.stdout = sys.stderr  # anything main.py prints stays off the protocol
    harness.block_sockets()
    base = tempfile.mkdtemp(prefix="decky-translator-bridge-")
    harness.install_decky(base)
    plugin_main = harness.import_main()
    windows = harness.FakeWindows().install(plugin_main)
    settings_dir = os.path.join(base, "plugin-settings")
    os.environ["DECKY_PLUGIN_SETTINGS_DIR"] = settings_dir
    with harness.Network():
        backend = harness.Backend(plugin_main, settings_dir, SETTINGS).start()
        out.write(json.dumps({"ready": True}) + "\n")
        out.flush()
        for line in sys.stdin:
            if not line.strip():
                continue
            req = json.loads(line)
            try:
                if req["method"] == "__restart__":
                    backend.stop()
                    backend = harness.Backend(plugin_main, settings_dir).start()
                    result = True
                elif req["method"] == "__windows__":
                    result = windows_state(windows)
                elif req["method"].startswith("_") or not hasattr(backend.plugin, req["method"]):
                    raise AttributeError(f"main.py has no method {req['method']}")  # Decky: the call fails
                else:
                    result = backend.call(req["method"], *req.get("args", []))
                resp = {"id": req["id"], "result": result}
            except Exception as e:  # noqa: BLE001 - sent to the frontend as the call's error
                traceback.print_exc()
                resp = {"id": req["id"], "error": f"{type(e).__name__}: {e}"}
            out.write(json.dumps(resp, default=str) + "\n")
            out.flush()
        backend.stop()


if __name__ == "__main__":
    main()
