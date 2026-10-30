# Tests

| Folder | What | Runs |
|---|---|---|
| `tests/backend` | `main.py` without Decky, Steam or a game (`harness.py`): settings, capture → OCR → translation → overlay, the Google → Bing fallback, the cache, errors, the game pause. HTTP is stubbed with `responses`. | CI, `python -m pytest` |
| `tests/python` | Unit tests of single Python modules. | CI, `python -m pytest` |
| `tests/frontend` | Every backend method the frontend calls exists in `main.py`; `deckyState.ts` edge cases. | CI, `pnpm test` |
| `tests/e2e` | The real device: Steam, Decky, The Banner Saga, real keys and screenshots. The check before a release. | device only, `pnpm test:e2e` |

## Running

```powershell
corepack pnpm install
corepack pnpm test
```

The Python tests need Python 3.14 with the plugin's packages and the test packages. Keep the virtual environment on a
short path: pywinrt's DLLs fail to load from deep folders.

```powershell
py -3.14 -m venv C:\venvs\windecky-tests
C:\venvs\windecky-tests\Scripts\python -m pip install --require-hashes -r requirements-windows.txt -r requirements-dev.txt
C:\venvs\windecky-tests\Scripts\python -m pytest
```
