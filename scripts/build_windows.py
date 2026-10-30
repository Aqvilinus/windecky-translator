"""Build the Windows release: the plugin zip and plugin-dependencies.tar.gz, the way upstream's Linux build does.

    python scripts/build_windows.py --version 0.9.1-win.1 [--repo owner/name] [--skip-frontend] [--out out]

- plugin-dependencies.tar.gz: py_modules/ (requirements-windows.txt as cp314 win_amd64 wheels) and python314/ (portable
  CPython 3.14 for Windows, python-build-standalone, SHA-256 pinned). Decky Loader downloads it with the plugin
  (package.json remote_binary, its hash checked) into bin/, main.py extracts it on the first start.
- decky-translator-windows.zip: the plugin (folder decky-translator/), its package.json pointing remote_binary at
  https://github.com/<repo>/releases/download/<version>/plugin-dependencies.tar.gz with the archive's SHA-256.
  Install it in Decky's developer settings (Install Plugin from URL / from ZIP file).

Runs on the windows-latest runner (.github/workflows/build-windows.yml) and locally (needs node + pnpm through
corepack unless --skip-frontend). Uses only the standard library, plus pip.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PYTHON_URL = ("https://github.com/astral-sh/python-build-standalone/releases/download/20261026/"
              "cpython-3.14.10%2B20261026-x86_64-pc-windows-msvc-install_only_stripped.tar.gz")
PYTHON_SHA256 = "c1876a9795d3a94ee49a1499a69cd91e26ca3e2829593f93fa6e4db90d05402b"

DEPENDENCIES_NAME = "plugin-dependencies.tar.gz"
ZIP_NAME = "decky-translator-windows.zip"
PLUGIN_FOLDER = "decky-translator"

# What Decky's CLI puts in a plugin zip (no source maps, no frontend sources)
PLUGIN_FILES = ["main.py", "plugin.json", "LICENSE", "README.md", "THIRD_PARTY_LICENSES"]
PLUGIN_DIRS = ["py_modules/providers", "py_modules/winport"]

# Not needed at runtime (as upstream strips them)
STRIP_DIRS = {"tests", "test", "testing", "__pycache__"}


def run(cmd, **kw):
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_frontend():
    pnpm = ["corepack", "pnpm"] if shutil.which("corepack") else ["pnpm"]
    shell = sys.platform == "win32"  # corepack/pnpm are .cmd shims on Windows
    run(pnpm + ["install", "--frozen-lockfile"], cwd=ROOT, shell=shell)
    run(pnpm + ["run", "build"], cwd=ROOT, shell=shell)


def build_py_modules(target):
    # requirements-windows.txt is the full lock (made from requirements-windows.in): every package pinned with its
    # hashes, so nothing unpinned or altered gets into the archive
    run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir",
         "--require-hashes", "--no-deps",
         "-r", os.path.join(ROOT, "requirements-windows.txt"), "--target", target,
         "--platform", "win_amd64", "--python-version", "3.14", "--implementation", "cp", "--only-binary=:all:"])
    for dirpath, dirnames, filenames in os.walk(target, topdown=True):
        for d in [d for d in dirnames if d in STRIP_DIRS]:
            shutil.rmtree(os.path.join(dirpath, d))
            dirnames.remove(d)
        for f in filenames:
            if f.endswith((".pyc", ".pyi")):
                os.remove(os.path.join(dirpath, f))
    shutil.rmtree(os.path.join(target, "bin"), ignore_errors=True)  # console-script launchers
    # RapidOCR's bundled models aren't used (the plugin downloads its own), but rapidocr 3 needs the folder
    models = os.path.join(target, "rapidocr", "models")
    shutil.rmtree(models, ignore_errors=True)
    os.makedirs(models)
    shutil.rmtree(os.path.join(target, "onnxruntime", "datasets"), ignore_errors=True)


def fetch_python(target, cache_dir):
    archive = os.path.join(cache_dir, "cpython-3.14-windows.tar.gz")
    if not (os.path.exists(archive) and sha256_of(archive) == PYTHON_SHA256):
        print(f"Downloading {PYTHON_URL}", flush=True)
        urllib.request.urlretrieve(PYTHON_URL, archive)
    if sha256_of(archive) != PYTHON_SHA256:
        raise SystemExit("Python runtime checksum mismatch")
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(target, filter="data")  # -> python314/python/python.exe
    if not os.path.exists(os.path.join(target, "python", "python.exe")):
        raise SystemExit("python.exe missing from the Python runtime archive")


def make_dependencies(work, out):
    deps = os.path.join(work, "deps")
    shutil.rmtree(deps, ignore_errors=True)
    os.makedirs(deps)
    build_py_modules(os.path.join(deps, "py_modules"))
    fetch_python(os.path.join(deps, "python314"), work)
    path = os.path.join(out, DEPENDENCIES_NAME)
    with tarfile.open(path, "w:gz") as tar:
        tar.add(os.path.join(deps, "py_modules"), arcname="py_modules")
        tar.add(os.path.join(deps, "python314"), arcname="python314")
    return path


def make_zip(out, version, repo, deps_sha):
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
    ap.add_argument("--version", required=True, help="release tag and plugin version, e.g. 0.9.1-win.1")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "Aqvilinus/windecky-translator"))
    ap.add_argument("--out", default=os.path.join(ROOT, "out"))
    ap.add_argument("--skip-frontend", action="store_true", help="use the existing dist/")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    work = os.path.join(ROOT, "dependencies_build")  # git-ignored, like upstream's
    os.makedirs(work, exist_ok=True)
    if not args.skip_frontend:
        build_frontend()
    if not os.path.exists(os.path.join(ROOT, "dist", "index.js")):
        raise SystemExit("dist/index.js missing: build the frontend first")

    deps = make_dependencies(work, args.out)
    deps_sha = sha256_of(deps)
    plugin_zip = make_zip(args.out, args.version, args.repo, deps_sha)
    print(f"{deps}: {os.path.getsize(deps) / 1e6:.1f} MB, sha256 {deps_sha}")
    print(f"{plugin_zip}: {os.path.getsize(plugin_zip) / 1e6:.1f} MB")
    if os.environ.get("GITHUB_STEP_SUMMARY"):  # shown on the workflow run's page
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(f"`{DEPENDENCIES_NAME}` sha256: `{deps_sha}`\n")


if __name__ == "__main__":
    main()
