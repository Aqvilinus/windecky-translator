# Development

You need Node.js (pnpm comes through `corepack`) and [uv](https://docs.astral.sh/uv/) (`winget install astral-sh.uv`).

```powershell
git clone https://github.com/Aqvilinus/windecky-translator.git "$env:USERPROFILE\homebrew\plugins\decky-translator"
cd "$env:USERPROFILE\homebrew\plugins\decky-translator"
corepack pnpm install
corepack pnpm run build
uv run python scripts/build_windows.py --version dev --skip-frontend
```

The last command builds `out/plugin-dependencies.tar.gz`; copy it into `bin/`, and the plugin unpacks it on its next start. Installing a release zip over a clone replaces the clone.

## Tests

- `corepack pnpm run typecheck`, `corepack pnpm test` and `uv run pytest`: the type check and the tests ([tests/README.md](tests/README.md)). CI runs them on every push.
- `uv lock --upgrade` updates the Python packages in `uv.lock` (the versions are in `pyproject.toml`).
- `corepack pnpm test:e2e`: end-to-end tests on the device, run from the plugin folder (it needs `bin/`). It needs Steam Big Picture with Decky Loader and an installed Steam game (The Banner Saga by default; set `E2E_APPID` and `E2E_WINDOW` for another one). It starts the game, translates with Ctrl+Alt+T and the side menu button, reloads the plugin and checks the screen (screenshots go to `tests/e2e/artifacts`). It takes over the screen and keyboard for about a minute.

## Releases

Versions follow [semantic versioning](https://semver.org/); the release tag is the version from `package.json` without a prefix (`1.0.0`).

To release, run the **Build Windows** workflow from the Actions tab with `release_version` set to the new version. It builds the zip and `plugin-dependencies.tar.gz` and publishes them as a draft release with that tag.
