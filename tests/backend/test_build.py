"""scripts/build_windows.py: THIRD_PARTY_LICENSES lists every Python package the archive ships, from its metadata."""
import importlib.util
import os
import sysconfig
from email.message import Message

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
spec = importlib.util.spec_from_file_location("build_windows", os.path.join(ROOT, "scripts", "build_windows.py"))
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def meta(**fields):
    m = Message()
    for key, values in fields.items():
        for v in values if isinstance(values, list) else [values]:
            m[key.replace("_", "-")] = v
    return m


def test_license_of_prefers_the_spdx_expression():
    assert build.license_of(meta(License_Expression="MIT", License="whatever")) == "MIT"
    assert build.license_of(meta(License="BSD-3-Clause")) == "BSD-3-Clause"
    assert build.license_of(meta(License="Copyright (c) ...\nPermission is hereby granted",
                                 Classifier=["License :: OSI Approved :: MIT License"])) == "MIT License"
    assert build.license_of(meta()) == "see its .dist-info folder"


def test_third_party_licenses_lists_the_installed_packages():
    text = build.third_party_licenses(sysconfig.get_paths()["purelib"])  # this environment's packages
    assert text.startswith("Third-party software in WinDecky Translator")
    assert "\npillow " in text.lower() and "MIT-CMU" in text
