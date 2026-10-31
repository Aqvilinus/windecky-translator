# providers/python_runtime.py
# The Python interpreter the worker subprocesses run on: the portable CPython 3.14 for Windows that
# plugin-dependencies.tar.gz (remote_binary, built by scripts/build_windows.py) puts in bin/python314, next to the cp314
# packages in bin/py_modules. 3.14 is also the version of Decky's frozen Python on Windows, so one py_modules serves
# the plugin process and the workers. A system Python is never used: it has other packages and maybe another version.

import logging
import os
import queue
import subprocess
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Must match the cpython ABI of the bundled C extensions (numpy, Pillow, ctranslate2, sentencepiece)
REQUIRED_PYTHON = (3, 14)

BUNDLED_PYTHON_RELPATH = os.path.join("bin", "python314", "python", "python.exe")

# Chrome Screen AI engine library inside its downloaded resources dir
SCREENAI_LIBRARY = "chrome_screen_ai.dll"

# The plugin's folder (py_modules/providers/ is two levels below it), for when DECKY_PLUGIN_DIR isn't set
PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_cached_path: Optional[str] = None


def worker_pythonpath(plugin_dir: str) -> str:
    """PYTHONPATH for the worker subprocesses: bin/py_modules (pip packages), then py_modules (plugin source)."""
    candidates = [os.path.join(plugin_dir, "bin", "py_modules"), os.path.join(plugin_dir, "py_modules")]
    paths = [p for p in candidates if os.path.exists(p)]
    return os.pathsep.join(paths) if paths else os.path.join(plugin_dir, "py_modules")


def missing_message() -> str:
    return ("Python 3.14 runtime missing (bin/python314). Reinstall the plugin from its release zip: Decky "
            "Loader downloads the runtime with it.")


def popen_kwargs() -> dict:
    """Extra subprocess arguments: no console window (it would pop up over the game)."""
    return {"creationflags": subprocess.CREATE_NO_WINDOW}


def readline_with_timeout(stream, timeout: float) -> Optional[bytes]:
    """stream.readline() that gives up after timeout seconds (None). select() can't wait on pipes on Windows."""
    result: "queue.Queue[bytes]" = queue.Queue()
    threading.Thread(target=lambda: result.put(stream.readline()), daemon=True).start()
    try:
        return result.get(timeout=timeout)
    except queue.Empty:
        return None


def find_python(plugin_dir: str) -> Optional[str]:
    """Path of the bundled interpreter if it is there and is REQUIRED_PYTHON, else None."""
    global _cached_path
    if _cached_path and os.path.exists(_cached_path):
        return _cached_path

    bundled = os.path.join(plugin_dir, BUNDLED_PYTHON_RELPATH)
    if os.path.exists(bundled):
        if _is_compatible(bundled):
            logger.debug(f"Using bundled Python: {bundled}")
            _cached_path = bundled
            return bundled
        logger.warning(f"Bundled Python at {bundled} failed version check")
    return None


def _is_compatible(path: str) -> bool:
    """Verify the interpreter at path matches REQUIRED_PYTHON."""
    try:
        result = subprocess.run(
            [path, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
            capture_output=True,
            text=True,
            timeout=10,  # first start of a fresh runtime is slow under Defender
            **popen_kwargs(),
        )
        if result.returncode != 0:
            return False
        major, minor = map(int, result.stdout.strip().split())
        return (major, minor) == REQUIRED_PYTHON
    except Exception as e:
        logger.debug(f"Compatibility check failed for {path}: {e}")
        return False
