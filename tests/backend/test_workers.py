"""The engines' worker scripts run on the bundled portable Python, which has no aiohttp (Decky's own Python has):
they may import their sibling modules, never the plugin's providers package (its base module imports aiohttp)."""
import os

PROVIDERS = os.path.join(os.path.dirname(__file__), "..", "..", "py_modules", "providers")
WORKERS = ("chromescreenai_subprocess.py", "ct2_translate_worker.py", "language_detection.py")


def test_workers_import_no_plugin_package():
    for name in WORKERS:
        with open(os.path.join(PROVIDERS, name), encoding="utf-8") as f:
            source = f.read()
        assert "from providers" not in source and "import providers" not in source, name
