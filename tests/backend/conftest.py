import os

import pytest

import harness


@pytest.fixture(scope="session")
def main(tmp_path_factory):
    """main.py, imported once with Decky's module emulated (harness.install_decky)."""
    restore_sockets = harness.block_sockets()
    _, events = harness.install_decky(str(tmp_path_factory.mktemp("decky")))
    module = harness.import_main()
    module.test_events = events
    yield module
    restore_sockets()


@pytest.fixture
def windows(main):
    w = harness.FakeWindows().install(main)
    yield w
    w.restore(main)


@pytest.fixture
def net():
    with harness.Network() as n:
        yield n


# OCR.space for the screen text and the free Google translator: both answered by the stubs
DEFAULT_SETTINGS = {"ocr_provider": "ocrspace", "translation_provider": "freegoogle", "target_language": "en"}


@pytest.fixture
def start(main, windows, net, tmp_path, monkeypatch):
    """start(settings) -> a started harness.Backend with DEFAULT_SETTINGS + settings in its settings file.
    A second start() is a restart on the settings the first left (fresh=True writes them anew)."""
    settings_dir = str(tmp_path / "settings")
    monkeypatch.setenv("DECKY_PLUGIN_SETTINGS_DIR", settings_dir)
    main.test_events.clear()
    started = []

    def _start(settings=None, fresh=False, write_settings=True):
        write = write_settings and (fresh or not started)
        if started:
            started[-1].stop()
        b = harness.Backend(main, settings_dir, {**DEFAULT_SETTINGS, **(settings or {})} if write else None)
        started.append(b.start())
        return b

    yield _start
    if started:
        started[-1].stop()


@pytest.fixture
def backend(start):
    return start()


def pytest_report_header():
    return f"plugin: {harness.ROOT}"


os.environ.setdefault("PYTHONUTF8", "1")
