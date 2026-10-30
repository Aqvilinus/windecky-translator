# Contributing

You need Node.js (pnpm comes through `corepack`) and [uv](https://docs.astral.sh/uv/) (`winget install astral-sh.uv`).

## Build

```powershell
git clone https://github.com/Aqvilinus/windecky-translator.git "$env:USERPROFILE\homebrew\plugins\decky-translator"
cd "$env:USERPROFILE\homebrew\plugins\decky-translator"
corepack pnpm install
corepack pnpm run build
uv run python scripts/build_windows.py --version dev --skip-frontend
```

The last command builds `out/plugin-dependencies.tar.gz`; copy it into `bin/`, and the plugin unpacks it on its next start. Installing a release zip over a clone replaces the clone.

`uv lock --upgrade` updates the Python packages in `uv.lock` (the versions are in `pyproject.toml`).

## Tests

```powershell
corepack pnpm run typecheck
corepack pnpm test      # tests/frontend: every backend method the frontend calls exists in main.py
uv run pytest           # tests/backend: main.py without Decky, Steam or a game, and single modules
corepack pnpm test:e2e  # tests/e2e: the real device
```

CI runs all but the last on every push. `test:e2e` is the check before a release: run it from the plugin folder Decky loads (it needs `bin/`), with Steam Big Picture and Decky Loader running and The Banner Saga installed (`E2E_APPID` and `E2E_WINDOW` pick another game). It starts the game, translates with Ctrl+Alt+T and the side menu button, reloads the plugin and checks the screen (screenshots go to `tests/e2e/artifacts`). It takes over the screen and keyboard for about a minute.

## Releases

Versions follow [semantic versioning](https://semver.org/); the release tag is the version from `package.json` without a prefix (`1.0.0`).

To release, run the **Build Windows** workflow from the Actions tab with `release_version` set to the new version. It builds the zip and `plugin-dependencies.tar.gz` and publishes them as a draft release with that tag.
