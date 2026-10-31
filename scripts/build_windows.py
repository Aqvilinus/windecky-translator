"""Build the Windows release: the plugin zip and plugin-dependencies.tar.gz.

    uv run python scripts/build_windows.py --version 1.0.0 [--repo owner/name] [--skip-frontend] [--out out]

- plugin-dependencies.tar.gz: py_modules/ (the packages in uv.lock) and python314/ (portable CPython 3.14 for the
  workers). Decky Loader downloads it with the plugin into bin/; main.py extracts it on the first start.
- decky-translator-windows.zip: the plugin, its package.json pointing remote_binary at the archive in the
  <version> release of <repo>, with the archive's SHA-256.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from importlib.metadata import distributions

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PYTHON_VERSION = "3.14.10"  # the portable runtime of the workers

DEPENDENCIES_NAME = "plugin-dependencies.tar.gz"
ZIP_NAME = "decky-translator-windows.zip"
PLUGIN_FOLDER = "decky-translator"

# What Decky's CLI puts in a plugin zip (no source maps, no frontend sources)
PLUGIN_FILES = ["main.py", "plugin.json", "LICENSE", "README.md"]  # + THIRD_PARTY_LICENSES, completed by the build
PLUGIN_DIRS = ["py_modules"]  # the plugin's own Python packages, whatever their names

# Not needed at runtime (as upstream strips them)
STRIP_DIRS = {"tests", "test", "testing", "__pycache__"}


def run(cmd, **kw):
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def sha256_of(path):
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def build_frontend():
    pnpm = ["corepack", "pnpm"] if shutil.which("corepack") else ["pnpm"]
    shell = sys.platform == "win32"  # corepack/pnpm are .cmd shims on Windows
    run(pnpm + ["install", "--frozen-lockfile"], cwd=ROOT, shell=shell)
    run(pnpm + ["run", "build"], cwd=ROOT, shell=shell)


def build_py_modules(target, work):
    # uv.lock pins every package with its hashes, so nothing unpinned or altered gets into the archive
    requirements = os.path.join(work, "requirements.txt")
    run(["uv", "export", "--locked", "--no-dev", "--no-emit-project", "--quiet", "-o", requirements], cwd=ROOT)
    run(["uv", "pip", "install", "--no-deps", "--require-hashes", "--no-build", "--target", target,
         "--python-platform", "x86_64-pc-windows-msvc", "--python-version", "3.14", "-r", requirements])
    for dirpath, dirnames, filenames in os.walk(target, topdown=True):
        for d in [d for d in dirnames if d in STRIP_DIRS]:
            shutil.rmtree(os.path.join(dirpath, d))
            dirnames.remove(d)
        for f in filenames:
            if f.endswith((".pyc", ".pyi")):
                os.remove(os.path.join(dirpath, f))
    shutil.rmtree(os.path.join(target, "bin"), ignore_errors=True)  # console-script launchers
    os.remove(os.path.join(target, ".lock"))  # uv's install lock


def fetch_python(target, work):
    # uv downloads python-build-standalone's build and checks its SHA-256
    installs = os.path.join(work, "python")
    run(["uv", "python", "install", PYTHON_VERSION, "--install-dir", installs, "--no-bin", "--no-registry"])
    shutil.copytree(os.path.join(installs, f"cpython-{PYTHON_VERSION}-windows-x86_64-none"),
                    os.path.join(target, "python"))  # -> python314/python/python.exe


def license_of(meta):
    """A package's license as its metadata states it: the SPDX expression, else a short License field, else the
    trove classifiers."""
    if meta.get("License-Expression"):
        return meta["License-Expression"]
    text = (meta.get("License") or "").strip()
    if text and "\n" not in text and len(text) <= 40:
        return text
    classifiers = [c.split(" :: ")[-1] for c in meta.get_all("Classifier") or [] if c.startswith("License :: ")]
    return ", ".join(classifiers) or "see its .dist-info folder"


def third_party_licenses(py_modules):
    """THIRD_PARTY_LICENSES: the hand-written part (runtime, frontend, downloads) and the Python packages actually
    in the archive, read from their metadata, so the list can't fall behind uv.lock."""
    with open(os.path.join(ROOT, "THIRD_PARTY_LICENSES"), encoding="utf-8") as f:
        text = f.read().rstrip() + "\n\n"
    packages = sorted(distributions(path=[py_modules]), key=lambda d: d.metadata["Name"].lower())
    if not packages:
        raise SystemExit(f"no packages found in {py_modules}")
    for d in packages:
        text += f"{d.metadata['Name']} {d.version}: {license_of(d.metadata)}\n"
    return text


def make_dependencies(work, out):
    deps = os.path.join(work, "deps")
    shutil.rmtree(deps, ignore_errors=True)
    os.makedirs(deps)
    build_py_modules(os.path.join(deps, "py_modules"), work)
    fetch_python(os.path.join(deps, "python314"), work)
    path = os.path.join(out, DEPENDENCIES_NAME)
    with tarfile.open(path, "w:gz") as tar:
        tar.add(os.path.join(deps, "py_modules"), arcname="py_modules")
        tar.add(os.path.join(deps, "python314"), arcname="python314")
    return path, third_party_licenses(os.path.join(deps, "py_modules"))


def make_zip(out, version, repo, deps_sha, licenses):
    with open(os.path.join(ROOT, "package.json"), encoding="utf-8") as f:
        package = json.load(f)
    package["version"] = version
    package["remote_binary"] = [{
        "name": DEPENDENCIES_NAME,
        "url": f"https://github.com/{repo}/releases/download/{version}/{DEPENDENCIES_NAME}",
        "sha256hash": deps_sha,
    }]
    path = os.path.join(out, ZIP_NAME)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{PLUGIN_FOLDER}/package.json", json.dumps(package, indent=2, ensure_ascii=False) + "\n")
        z.writestr(f"{PLUGIN_FOLDER}/THIRD_PARTY_LICENSES", licenses)
        for name in PLUGIN_FILES:
            z.write(os.path.join(ROOT, name), f"{PLUGIN_FOLDER}/{name}")
        dist = os.path.join(ROOT, "dist")
        for dirpath, _, filenames in os.walk(dist):
            for f in filenames:
                if not f.endswith(".map"):
                    full = os.path.join(dirpath, f)
                    z.write(full, f"{PLUGIN_FOLDER}/dist/" + os.path.relpath(full, dist).replace(os.sep, "/"))
        for d in PLUGIN_DIRS:
            base = os.path.join(ROOT, d)
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = [x for x in dirnames if x != "__pycache__"]
                for f in filenames:
                    full = os.path.join(dirpath, f)
                    z.write(full, f"{PLUGIN_FOLDER}/" + os.path.relpath(full, ROOT).replace(os.sep, "/"))
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--version", required=True, help="plugin version and release tag, e.g. 1.0.0 (no \"v\")")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "Aqvilinus/windecky-translator"))
    ap.add_argument("--out", default=os.path.join(ROOT, "out"))
    ap.add_argument("--skip-frontend", action="store_true", help="use the existing dist/")
    args = ap.parse_args()
    if re.match(r"v\d", args.version):  # the tag is the bare version, so a "v" would end up in the plugin's version
        raise SystemExit(f"--version {args.version}: give it without the v ({args.version[1:]}), the tag is the same")

    os.makedirs(args.out, exist_ok=True)
    work = os.path.join(ROOT, "dependencies_build")  # git-ignored, like upstream's
    os.makedirs(work, exist_ok=True)
    if not args.skip_frontend:
        build_frontend()
    if not os.path.exists(os.path.join(ROOT, "dist", "index.js")):
        raise SystemExit("dist/index.js missing: build the frontend first")

    deps, licenses = make_dependencies(work, args.out)
    deps_sha = sha256_of(deps)
    plugin_zip = make_zip(args.out, args.version, args.repo, deps_sha, licenses)
    print(f"{deps}: {os.path.getsize(deps) / 1e6:.1f} MB, sha256 {deps_sha}")
    print(f"{plugin_zip}: {os.path.getsize(plugin_zip) / 1e6:.1f} MB")
    if os.environ.get("GITHUB_STEP_SUMMARY"):  # shown on the workflow run's page
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(f"`{DEPENDENCIES_NAME}` sha256: `{deps_sha}`\n")


if __name__ == "__main__":
    main()
