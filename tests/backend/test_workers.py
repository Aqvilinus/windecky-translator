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


def test_providers_load_without_compiled_modules():
    """main.py imports the providers package unguarded: it must load even when Pillow (built for one Python version)
    can't, so the plugin still starts and reports what is missing (main.py _BOOT_ERRORS)."""
    import subprocess
    import sys
    code = ("import sys; sys.modules['PIL'] = None; sys.modules['numpy'] = None; "
            f"sys.path.insert(0, {os.path.dirname(PROVIDERS)!r}); import providers")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
