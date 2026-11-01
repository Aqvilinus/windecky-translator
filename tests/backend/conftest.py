import os
import tempfile

import pytest

import harness

# Decky's module emulated before any test module imports the plugin's (game_process reads its runtime folder)
_DECKY_DIR = tempfile.TemporaryDirectory()
_, DECKY_EVENTS = harness.install_decky(_DECKY_DIR.name)


@pytest.fixture(scope="session")
def main():
    """main.py, imported once."""
    restore_sockets = harness.block_sockets()
    module = harness.import_main()
    module.test_events = DECKY_EVENTS
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


# Google Cloud Vision for the screen text and the free Google translator: both answered by the stubs
DEFAULT_SETTINGS = {"ocr_provider": "google_cloud", "google_api_key": "test-key-0123456789",
                    "translation_provider": "google_web", "target_language": "en"}


@pytest.fixture
def start(main, windows, net, tmp_path):
    """start(settings) -> a started harness.Backend with DEFAULT_SETTINGS + settings in its settings file.
    A second start() is a restart on the settings the first left (fresh=True writes them anew)."""
    main.test_events.clear()
    started = []

    def _start(settings=None, fresh=False, write_settings=True):
        write = write_settings and (fresh or not started)
        if started:
            started[-1].stop()
        b = harness.Backend(main, str(tmp_path), {**DEFAULT_SETTINGS, **(settings or {})} if write else None)
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
