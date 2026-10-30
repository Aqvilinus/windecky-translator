"""Puts the plugin's backend packages (py_modules) on sys.path for the Python unit tests."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY_MODULES = os.path.join(ROOT, "py_modules")
if PY_MODULES not in sys.path:
    sys.path.insert(0, PY_MODULES)
