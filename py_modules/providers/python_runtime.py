# providers/python_runtime.py
# Find a Python interpreter for subprocess execution.
# Prefers the bundled portable Python (extracted from plugin-dependencies.tar.gz)
# so the plugin works whatever Python the system has (SteamOS / any Linux distro; Windows).
# Falls back to a version-checked system Python for dev installs without
# the bundled runtime.

import logging
import os
import queue
import subprocess
import sys
import threading
from typing import Optional

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

# Must match the cpython ABI of the bundled C extensions
# (numpy, Pillow, onnxruntime, ctranslate2, sentencepiece — all cp313)
REQUIRED_PYTHON = (3, 13)

BUNDLED_PYTHON_RELPATH = os.path.join("bin", "python313", "python", "bin", "python3.13")

# Chrome Screen AI engine library inside its downloaded resources dir
SCREENAI_LIBRARY = "libchromescreenai.so"

if IS_WINDOWS:
    # Windows port: same scheme, own build. plugin-dependencies.tar.gz (remote_binary, built by
    # .github/workflows/build-windows.yml) holds a portable CPython 3.14 for Windows in bin/python314 and cp314
    # packages in bin/py_modules. 3.14 is the version of Decky's frozen Python on Windows, so one py_modules serves
    # the plugin process and the workers.
    REQUIRED_PYTHON = (3, 14)
    BUNDLED_PYTHON_RELPATH = os.path.join("bin", "python314", "python", "python.exe")
    SCREENAI_LIBRARY = "chrome_screen_ai.dll"

_cached_path: Optional[str] = None


def worker_pythonpath(plugin_dir: str) -> str:
    """PYTHONPATH for the worker subprocesses: bin/py_modules (pip packages), then py_modules (plugin source)."""
    candidates = [os.path.join(plugin_dir, "bin", "py_modules"), os.path.join(plugin_dir, "py_modules")]
    paths = [p for p in candidates if os.path.exists(p)]
    return os.pathsep.join(paths) if paths else os.path.join(plugin_dir, "py_modules")


def missing_message() -> str:
    if IS_WINDOWS:
        return ("Python 3.14 runtime missing (bin/python314). Reinstall the plugin from its release zip: Decky "
                "Loader downloads the runtime with it.")
    return ("Python 3.13 runtime missing. Reinstall the plugin to restore "
            "the bundled runtime, or install python3.13 on your system.")


def popen_kwargs() -> dict:
    """Extra subprocess arguments: on Windows no console window (it would pop up over the game)."""
    if IS_WINDOWS:
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def readline_with_timeout(stream, timeout: float) -> Optional[bytes]:
    """stream.readline() that gives up after timeout seconds (None). select() can't wait on pipes on Windows."""
    if not IS_WINDOWS:
        import select
        ready, _, _ = select.select([stream], [], [], timeout)
        return stream.readline() if ready else None
    result: "queue.Queue[bytes]" = queue.Queue()
    threading.Thread(target=lambda: result.put(stream.readline()), daemon=True).start()
    try:
        return result.get(timeout=timeout)
    except queue.Empty:
        return None


def find_python(plugin_dir: str) -> Optional[str]:
    """
    Return path to a Python interpreter compatible with bundled cp313 wheels.

    Resolution order:
        1. Bundled portable Python under <plugin_dir>/bin/python313/
        2. System python3.13 (verified against REQUIRED_PYTHON)
        3. System python3 symlink (verified against REQUIRED_PYTHON)
    """
    global _cached_path
    if _cached_path and os.path.exists(_cached_path):
        return _cached_path

    bundled = os.path.join(plugin_dir, BUNDLED_PYTHON_RELPATH)
    if os.path.exists(bundled) and os.access(bundled, os.X_OK):
        if _is_compatible(bundled):
            logger.debug(f"Using bundled Python: {bundled}")
            _cached_path = bundled
            return bundled
        logger.warning(f"Bundled Python at {bundled} failed version check")

    if IS_WINDOWS:
        return None  # only the downloaded runtime: a system Python has other packages and maybe another version

    candidates = [
        "/usr/bin/python3.13",
        "/usr/local/bin/python3.13",
        "/usr/bin/python3",
        "/usr/local/bin/python3",
    ]
    for path in candidates:
        if not (os.path.exists(path) and os.access(path, os.X_OK)):
            continue
        if _is_compatible(path):
            logger.debug(f"Using system Python: {path}")
            _cached_path = path
            return path

    logger.warning(
        f"No compatible Python {REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]} interpreter found"
    )
    return None


def _is_compatible(path: str) -> bool:
    """Verify the interpreter at path matches REQUIRED_PYTHON."""
    try:
        result = subprocess.run(
            [path, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
            capture_output=True,
            text=True,
            timeout=10 if IS_WINDOWS else 3,  # first start of a fresh runtime is slow under Defender
            **popen_kwargs(),
        )
        if result.returncode != 0:
            return False
        major, minor = map(int, result.stdout.strip().split())
        return (major, minor) == REQUIRED_PYTHON
    except Exception as e:
        logger.debug(f"Compatibility check failed for {path}: {e}")
        return False


def reset_cache() -> None:
    """Clear the cached interpreter path. Used by tests / after re-extraction."""
    global _cached_path
    _cached_path = None
