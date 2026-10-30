# Tests

Everything but `tests/e2e` runs without Steam, Decky Loader or a game, and never reaches a real service: CI
(`.github/workflows/build-windows.yml`) runs it on every push and pull request.

| Folder | What | Runs |
|---|---|---|
| `tests/integration` | The built plugin (`dist/index.js`) in an emulated Steam + Decky Loader, driven like a user: Translate in the side menu over a game, Ctrl+Alt+T, a side menu opened over the translation, a plugin reload with the side menu open on it. Checks what reaches the backend and what the side menu shows. | CI, `pnpm test` |
| `tests/integration/contract.test.ts` | The same frontend calling the real `main.py` (both halves for real: arguments and results each side reads). | CI, `pnpm test` with `PLUGIN_PYTHON` set |
| `tests/backend` | `main.py` driven through the frontend's calls: settings, capture → OCR → translation → overlay drawing, the Google → Bing fallback, the cache, errors, the game pause, the hotkey event. | CI, `python -m pytest` |
| `tests/python` | Unit tests of single Python modules (unittest style). | CI, `python -m pytest` |
| `tests/frontend` | Unit tests: every backend method the frontend calls exists in `main.py`; `deckyState.ts` timer edge cases. | CI, `pnpm test` |
| `tests/e2e` | The real device: Steam, Decky, The Banner Saga, real keys, real screenshots. The final smoke check before a release (what only it covers is at the top of `translate.e2e.mjs`). | device only, `pnpm test:e2e` |

## Running

```powershell
corepack pnpm install
corepack pnpm test                    # builds dist/ first (SKIP_PLUGIN_BUILD=1 uses the one there)
```

The Python tests need Python 3.14 with the plugin's packages and the test packages, both hashed locks. Keep the
virtual environment on a short path: pywinrt's DLLs fail to load from deep folders.

```powershell
py -3.14 -m venv C:\venvs\windecky-tests
C:\venvs\windecky-tests\Scripts\python -m pip install --require-hashes -r requirements-windows.txt -r requirements-dev.txt
C:\venvs\windecky-tests\Scripts\python -m pytest
$env:PLUGIN_PYTHON = "C:\venvs\windecky-tests\Scripts\python.exe"; corepack pnpm test   # with the contract tests
```

`requirements-dev.in` says how to regenerate `requirements-dev.txt`.

## How the emulation works

- `integration/steam.ts`: Steam's SharedJSContext as the bundle sees it. Rollup turns the plugin's imports into
  globals (`SP_REACT`, `DFL`, `SteamClient`); this installs React, plain-HTML stand-ins for `@decky/ui`'s components
  (buttons are `<button>`, toggles checkboxes), and `Router` with a menu store per Steam UI window: Big Picture, and
  an overlay window per running game. `Router.CloseSideMenus()` acts on Big Picture only, as in Steam.
- `integration/decky.ts`: Decky Loader's frontend: the API `@decky/api` connects to (`call`, events, `routerHook`,
  `toaster`), `deckyState` with `_plugins` / `_activePlugin`, and loading the bundle the way Decky's plugin loader
  does. A reload keeps `_activePlugin` pointing at the unloaded instance, as real Decky does.
- `integration/fakeBackend.ts`: main.py's answers, scripted; a method it doesn't know fails the test.
- `backend/harness.py`: main.py with Decky's module emulated and its Windows parts replaced at main.py's own names
  (`capture_foreground`, `Overlay`, `GameHotkey`, `winprocess`): the capture returns a test image, the overlay window
  records what it is told and draws it with the real `winport.overlay.render`. HTTP goes through `responses`, with
  Google Translate, Bing and OCR.space stubbed; any other connection fails.

The emulation follows what the real Steam and Decky did on the device. When they change, `pnpm test:e2e` is what
notices; update the emulation to match.
