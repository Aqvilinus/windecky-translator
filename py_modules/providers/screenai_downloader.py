# providers/screenai_downloader.py
# Chrome's on-device OCR engine (chrome_screen_ai.dll + TFLite models), fetched from Google's CIPD package server

import json
import logging
import os
import re
import shutil
import urllib.error
import urllib.request
import zipfile

from .model_download import DownloadError, ModelDownload
from .python_runtime import SCREENAI_LIBRARY

logger = logging.getLogger(__name__)

# Chrome's Screen AI component for Windows x64 (an ~80 MB zip)
CIPD_PACKAGE = "chromium/third_party/screen-ai/windows-amd64"
# Accepts a tag/ref or a 64-char SHA256 digest; "latest" tracks Chrome Stable.
CIPD_VERSION = "latest"
CIPD_HOST = "https://chrome-infra-packages.appspot.com"
PRPC_RESOLVE = f"{CIPD_HOST}/prpc/cipd.Repository/ResolveVersion"
PRPC_GET_URL = f"{CIPD_HOST}/prpc/cipd.Repository/GetInstanceURL"
# pRPC responses are prefixed with )]}' to defeat JSON hijacking.
PRPC_PREFIX = b")]}'"

APPROX_SIZE_MB = 80
# CIPD package nests everything under resources/ at the zip root.
RESOURCES_SUBDIR = "resources"


class ScreenAIDownload(ModelDownload):
    name = "screen_ai"
    approx_size_mb = APPROX_SIZE_MB
    required_files = (os.path.join(RESOURCES_SUBDIR, SCREENAI_LIBRARY),)

    @property
    def resources_dir(self) -> str:
        """The OCR worker's model_dir: the DLL loads its TFLite models from paths relative to its own folder."""
        return os.path.join(self.target_dir, RESOURCES_SUBDIR)

    def _install(self, staging_dir: str) -> None:
        signed_url, hash_algo, hex_digest = self._resolve_signed_url()
        self._check_cancel()
        package = os.path.join(staging_dir, "package.zip")
        # the package holds a native library the OCR worker loads: check it is exactly the instance CIPD named
        try:
            digest = self._fetch(signed_url, package, hash_name=hash_algo.lower(),
                                 progress=lambda f: self._set_progress(f * 0.95))  # the rest is the unzip
        except ValueError as e:  # hashlib doesn't know the algorithm
            raise DownloadError(f"Unsupported package hash: {hash_algo}") from e
        if digest != str(hex_digest).lower():
            raise DownloadError("Downloaded package is damaged or not the expected one (hash mismatch)")
        logger.info(f"Chrome Screen AI package verified ({hash_algo} {hex_digest[:12]}...)")
        try:
            with zipfile.ZipFile(package) as zf:
                zf.extractall(staging_dir)
        except zipfile.BadZipFile as e:
            raise DownloadError("Downloaded package is not a valid zip") from e
        os.remove(package)
        shutil.rmtree(os.path.join(staging_dir, ".cipdpkg"), ignore_errors=True)  # CIPD's manifest

    def _prpc_post(self, url: str, payload: dict) -> dict:
        request = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=30) as resp:
                body = resp.read()
        except urllib.error.HTTPError as e:
            raise DownloadError(f"Package server: HTTP {e.code}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise DownloadError("Cannot reach the download server. Check the internet connection.") from e
        if body.startswith(PRPC_PREFIX):
            body = body[len(PRPC_PREFIX):]
        return json.loads(body.decode("utf-8"))

    def _resolve_signed_url(self):
        """(download URL, hash algorithm, hex digest): CIPD names an instance by the hash of its package file."""
        # ResolveVersion only takes tags/refs; a 64-char hex digest is already the instance
        if re.fullmatch(r"[0-9a-f]{64}", CIPD_VERSION):
            hash_algo, hex_digest = "SHA256", CIPD_VERSION
        else:
            resolved = self._prpc_post(PRPC_RESOLVE, {"package": CIPD_PACKAGE, "version": CIPD_VERSION})
            instance = resolved.get("instance") or {}
            hash_algo, hex_digest = instance.get("hashAlgo"), instance.get("hexDigest")
            if not hash_algo or not hex_digest:
                raise DownloadError(f"The package server named no package: {resolved}")
        url_resp = self._prpc_post(PRPC_GET_URL, {
            "package": CIPD_PACKAGE,
            "instance": {"hashAlgo": hash_algo, "hexDigest": hex_digest},
        })
        signed = url_resp.get("signedUrl")
        if not signed:
            raise DownloadError(f"The package server gave no download address: {url_resp}")
        return signed, hash_algo, hex_digest
