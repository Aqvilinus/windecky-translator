# WinDecky Translator

[![Release](https://img.shields.io/github/v/release/Aqvilinus/windecky-translator)](https://github.com/Aqvilinus/windecky-translator/releases)
[![Build](https://img.shields.io/github/actions/workflow/status/Aqvilinus/windecky-translator/build-windows.yml)](https://github.com/Aqvilinus/windecky-translator/actions/workflows/build-windows.yml)
[![License: GPL-3.0](https://img.shields.io/badge/license-GPL--3.0-green)](LICENSE)

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin for Steam Big Picture on Windows that translates the text in your game: it reads the screen and draws the translation over the original text.

![The Banner Saga main menu before and after translation into Russian](assets/screenshot.jpg)

A Windows port of [Decky Translator](https://github.com/cat-in-a-box/Decky-Translator) by cat-in-a-box.

## Features

- Translates any game, including ones that were never localized
- One button in the Decky side menu, or the **Ctrl+Alt+T** shortcut (which you can map to a controller button)
- Works for free and without an account; on-device engines also work offline
- AI translation with Groq, Gemini or your own server, for translations that keep the context
- Remembers translated lines, so text you've already seen shows up instantly

## Install

You need Windows 11, Steam in Big Picture mode and [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) for Windows.

1. Download `decky-translator-windows.zip` from the [latest release](https://github.com/Aqvilinus/windecky-translator/releases/latest).
2. In Big Picture, open the Quick Access menu, go to the Decky tab and open its settings.
3. Turn on **Developer Mode** (General tab), then in the **Developer** tab choose **Install Plugin from ZIP File** and pick the zip.

## How to use

In a game, open the Quick Access menu, go to the Decky tab, open **WinDecky Translator** and press **Translate**, or press **Ctrl+Alt+T**. Press it again to close the translation. Engines and languages are in the plugin's **Translation** tab.

## License

[GNU GPL v3.0](LICENSE); third-party components are listed in [THIRD_PARTY_LICENSES](THIRD_PARTY_LICENSES). Building and testing: [DEVELOPMENT.md](DEVELOPMENT.md).
