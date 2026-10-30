# Tests

| Folder | What | Runs |
|---|---|---|
| `tests/backend` | `main.py` without Decky, Steam or a game (`harness.py`): settings, capture → OCR → translation → overlay, the Google → Bing fallback, the cache, errors, the game pause. HTTP is stubbed with `responses`. | CI, `uv run pytest` |
| `tests/python` | Unit tests of single Python modules. | CI, `uv run pytest` |
| `tests/frontend` | Every backend method the frontend calls exists in `main.py`; `deckyState.ts` edge cases. | CI, `pnpm test` |
| `tests/e2e` | The real device: Steam, Decky, The Banner Saga, real keys and screenshots. The check before a release. | device only, `pnpm test:e2e` |

## Running

```powershell
corepack pnpm install
corepack pnpm test
uv run pytest
```
