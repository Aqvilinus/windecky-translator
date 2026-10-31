"""providers/model_download.py: a model download in its thread, staged and moved into place only when complete.
The 'server' is a local file (urllib reads file:// URLs too)."""
import hashlib
import os
import pathlib
import time

from providers.model_download import DownloadError, ModelDownload


def wait(download):
    for _ in range(200):
        if not download.status()["downloading"]:
            return download.status()
        time.sleep(0.01)
    raise AssertionError("the download didn't finish")


def make(tmp_path, content, expected_sha256=None, max_mb=None):
    source = tmp_path / "server" / "model.bin"
    source.parent.mkdir()
    source.write_bytes(content)
    url = pathlib.Path(source).as_uri()

    class Model(ModelDownload):
        name = "model"
        approx_size_mb = 1
        required_files = ("model.bin",)

        def _install(self, staging_dir):
            digest = self._fetch(url, os.path.join(staging_dir, "model.bin"), progress=self._set_progress,
                                 max_mb=max_mb)
            if expected_sha256 and digest != expected_sha256:
                raise DownloadError("hash mismatch")

    return Model(str(tmp_path / "models"))


def test_a_complete_download_is_installed(tmp_path):
    content = b"x" * 1000
    model = make(tmp_path, content, hashlib.sha256(content).hexdigest())
    assert model.status()["downloaded"] is False
    assert model.start() is True
    status = wait(model)
    assert status["downloaded"] and status["size"] == 1000 and status["progress"] == 1.0 and status["error"] is None
    assert model.delete() and not model.is_installed()


def test_a_damaged_download_is_not_installed(tmp_path):
    model = make(tmp_path, b"x" * 1000, expected_sha256="0" * 64)
    model.start()
    status = wait(model)
    assert status["error"] == "hash mismatch" and not status["downloaded"]
    assert not os.path.exists(model.target_dir + ".downloading")  # no partial files left


def test_a_download_bigger_than_expected_is_refused(tmp_path):
    model = make(tmp_path, b"x" * (2 * 1024 * 1024 + 1), max_mb=2)
    model.start()
    assert "more than expected" in wait(model)["error"]


def test_a_missing_file_on_the_server_is_an_error(tmp_path):
    model = make(tmp_path, b"x")
    os.remove(tmp_path / "server" / "model.bin")
    model.start()
    assert "Cannot reach the download server" in wait(model)["error"]
