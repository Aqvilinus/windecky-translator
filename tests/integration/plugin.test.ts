// @vitest-environment happy-dom
// The real plugin bundle in an emulated Steam (steam.ts) + Decky Loader (decky.ts), with the backend scripted
// (fakeBackend.ts). What the user does: open the side menu over a game, press Translate, press Ctrl+Alt+T, open a
// side menu over the translation, reload the plugin. What is checked: what reaches the backend (the overlay window
// on Windows draws exactly what native_overlay_update sends) and what the side menu shows.
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { BUNDLE } from './buildPlugin';
import { FakeDecky } from './decky';
import { FakeBackend } from './fakeBackend';
import { startSteam, stopSteam, type FakeSteam, type SteamWindow } from './steam';

const NAME = 'WinDecky Translator';
const GAME = { appid: '237990', name: 'The Banner Saga' };

let steam: FakeSteam;
let decky: FakeDecky;
let backend: FakeBackend;

async function waitFor<T>(what: string, check: () => T | undefined | null | false, timeoutMs = 3000): Promise<T> {
    const end = Date.now() + timeoutMs;
    for (;;) {
        const r = check();
        if (r) return r;
        if (Date.now() > end) throw new Error(`timed out waiting for ${what}`);
        await new Promise(res => setTimeout(res, 20));
    }
}
const sleep = (ms: number) => new Promise(res => setTimeout(res, ms));

const overlayUpdates = () => decky.calls.filter(c => c.method === 'native_overlay_update').map(c => c.args[0]);
const lastOverlay = () => overlayUpdates().at(-1);
const callsOf = (method: string) => decky.calls.filter(c => c.method === method);

function buttons(win: SteamWindow, text: string): HTMLButtonElement[] {
    return [...win.element.querySelectorAll('button')].filter(b => b.textContent?.trim() === text);
}

// The plugin's main button in that window's side menu ("Translate" / "Close Overlay")
const mainButton = (win: SteamWindow) => waitFor(`the plugin's button in ${win.name}`,
    () => win.isSideMenuOpen && (buttons(win, 'Translate')[0] ?? buttons(win, 'Close Overlay')[0]));

// Open the side menu in a window, on the plugin (Decky's list, then the plugin)
async function openPluginInSideMenu(win: SteamWindow) {
    win.setSideMenu(true);
    const entry = await waitFor('the plugin in the side menu', () =>
        win.element.querySelector('[data-decky-plugin]') || buttons(win, NAME)[0]);
    if (entry instanceof HTMLButtonElement) entry.click();
    return mainButton(win);
}

// A translation is on screen: the overlay window was sent the translated regions
const translationShown = (what: string) => waitFor(what, () => {
    const s = lastOverlay();
    return s?.visible && !s.loading && s.regions?.length && s;
}, 5000);

const translationHidden = (what: string) => waitFor(what, () => lastOverlay()?.visible === false && lastOverlay());

beforeEach(async () => {
    backend = new FakeBackend();
    steam = startSteam(() => decky.renderSideMenu());
    decky = new FakeDecky(backend, BUNDLE, NAME);
    await decky.loadPlugin();
});

afterEach(() => {
    decky.unload();
    stopSteam();
    document.body.innerHTML = '';
    expect(backend.unknownCalls, 'methods the fake backend does not know (add them to fakeBackend.ts)').toEqual([]);
});

describe('loading', () => {
    it('registers with Decky and hides a translation an earlier Steam UI left on screen', async () => {
        expect(decky.plugin?.name).toBe(NAME);
        await waitFor('the startup overlay update', () => overlayUpdates().length);
        expect(overlayUpdates()[0]).toEqual({ visible: false });
        expect(decky.listenerCount('translator_hotkey')).toBe(1);
        // no translation: opening a side menu shows nothing (settings loading there resend the hidden state)
        steam.bigPicture.setSideMenu(true);
        await sleep(400);
        expect(overlayUpdates().filter(s => s.visible)).toEqual([]);
    });

    it('reports the running Steam games to the backend', async () => {
        steam.launchGame(GAME.appid, GAME.name);
        await waitFor('set_steam_app', () => callsOf('set_steam_app').length);
        expect(callsOf('set_steam_app')[0].args).toEqual([237990, true, 1, false]);
    });
});

describe('translating over a game', () => {
    let overlay: SteamWindow;
    beforeEach(() => { overlay = steam.launchGame(GAME.appid, GAME.name); });

    it('Translate in the side menu closes the menu, captures the game and shows the translation', async () => {
        const translate = await openPluginInSideMenu(overlay);
        let callsWhenMenuClosed = -1;
        overlay.onSideMenu = open => { if (!open) callsWhenMenuClosed = decky.calls.length; };
        translate.click();
        const shown = await translationShown('the translation in the overlay window');

        // the side menu over the game was closed before the capture (else it is captured and translated too)
        expect(overlay.isSideMenuOpen).toBe(false);
        expect(callsWhenMenuClosed).toBeGreaterThan(-1);
        expect(decky.calls.findIndex(c => c.method === 'take_screenshot')).toBeGreaterThanOrEqual(callsWhenMenuClosed);
        expect(callsOf('take_screenshot').map(c => c.args)).toEqual([[GAME.name]]);
        expect(callsOf('recognize_text_file')[0].args[0]).toMatch(/The Banner Saga_\d+\.png$/);
        expect(shown.regions.map((r: any) => r.translatedText)).toEqual(['Welcome, traveller', 'New game']);
        expect(shown).toMatchObject({ processingIsError: false, translationsVisible: true });

        overlay.setSideMenu(true);  // opening the menu closes the translation (below); the button is back to Translate
        await translationHidden('the translation closed by the side menu');
        await waitFor('the button to say Translate', () => buttons(overlay, 'Translate')[0], 2000);
    });

    it('opening a side menu over the translation closes it, closing the menu does not bring it back', async () => {
        decky.emit('translator_hotkey');
        await translationShown('the translation after Ctrl+Alt+T');
        await sleep(600);
        expect(lastOverlay().visible).toBe(true);  // nothing closes it by itself

        overlay.setSideMenu(true);
        await translationHidden('the translation closed by the side menu');
        overlay.setSideMenu(false);
        await sleep(600);
        expect(lastOverlay().visible).toBe(false);
    });

    it('a side menu in Big Picture closes it too', async () => {
        decky.emit('translator_hotkey');
        await translationShown('the translation after Ctrl+Alt+T');
        steam.bigPicture.setSideMenu(true);
        await translationHidden('the translation closed by the Big Picture side menu');
    });

    it('Ctrl+Alt+T translates and closes the translation again', async () => {
        decky.emit('translator_hotkey');
        await translationShown('the translation after Ctrl+Alt+T');
        decky.emit('translator_hotkey');
        await translationHidden('the translation closed by Ctrl+Alt+T');
        expect(callsOf('take_screenshot').length).toBe(1);
    });

    it('Ctrl+Alt+T with the side menu open closes the menu before the capture', async () => {
        await openPluginInSideMenu(overlay);
        decky.emit('translator_hotkey');
        await translationShown('the translation after Ctrl+Alt+T');
        expect(overlay.isSideMenuOpen).toBe(false);
        // the translation appeared after the menu closed, so it stays
        await sleep(600);
        expect(lastOverlay().visible).toBe(true);
    });

    it('a side menu still closing when the translation appears does not close it', async () => {
        overlay.closeDelayMs = 1500;  // longer than the plugin waits for it (windows.ts closeAllSideMenus)
        await openPluginInSideMenu(overlay);
        decky.emit('translator_hotkey');
        await translationShown('the translation, with the menu still closing');
        await waitFor('the menu to finish closing', () => !overlay.isSideMenuOpen, 3000);
        await sleep(600);
        expect(lastOverlay().visible).toBe(true);
        overlay.setSideMenu(true);  // opened again: that one closes it
        await translationHidden('closed by the reopened side menu');
    });

    it('a network error shows the error, then hides the overlay', async () => {
        backend.handlers.translate_text = () => ({ error: 'network_error', message: 'No internet connection' });
        decky.emit('translator_hotkey');
        const err = await waitFor('the error in the overlay', () => {
            const s = lastOverlay();
            return s?.visible && s.processingIsError && s;
        });
        expect(err.processingStep).toBe('No internet connection');
        await waitFor('the overlay to hide after the error', () => lastOverlay()?.visible === false, 4000);
    });

    it('with the plugin disabled Translate is gone and Ctrl+Alt+T does nothing', async () => {
        await openPluginInSideMenu(overlay);
        const toggle = await waitFor('the enable toggle', () =>
            overlay.element.querySelector<HTMLInputElement>('[data-label="Plugin is enabled"] input'));
        toggle.click();
        await waitFor('set_setting enabled=false', () =>
            callsOf('set_setting').find(c => c.args[0] === 'enabled' && c.args[1] === false));
        await waitFor('the Translate button to go', () => !buttons(overlay, 'Translate').length);
        overlay.setSideMenu(false);
        decky.emit('translator_hotkey');
        await sleep(500);
        expect(callsOf('take_screenshot')).toEqual([]);
    });
});

describe('plugin reload (store update, disable/enable)', () => {
    it('the side menu open on the plugin shows the new instance, and its Translate works', async () => {
        const overlay = steam.launchGame(GAME.appid, GAME.name);
        await openPluginInSideMenu(overlay);
        const before = decky.plugin;

        await decky.loadPlugin();
        expect(backend.restarts).toBe(1);
        expect(decky.plugin).not.toBe(before);
        await waitFor('Decky to show the new instance in the side menu', () => decky.state._activePlugin === decky.plugin, 2000);
        expect(decky.listenerCount('translator_hotkey')).toBe(1);  // the old instance stopped listening

        overlay.setSideMenu(false);
        const translate = await openPluginInSideMenu(overlay);
        const sent = overlayUpdates().length;
        translate.click();
        await waitFor('the reloaded plugin to show the translation', () =>
            overlayUpdates().slice(sent).find(s => s.visible && !s.loading && s.regions?.length), 5000);
    });

    it('leaves another plugin open in the side menu alone', async () => {
        decky.state.setPlugins([...decky.state._plugins, { name: 'CSS Loader', version: '1', content: undefined }]);
        decky.state.setActivePlugin('CSS Loader');
        await decky.loadPlugin();
        await sleep(400);
        expect(decky.state._activePlugin?.name).toBe('CSS Loader');
    });

    it('the unloaded instance no longer closes or forwards translations', async () => {
        const overlay = steam.launchGame(GAME.appid, GAME.name);
        await decky.loadPlugin();
        decky.emit('translator_hotkey');
        await translationShown('the translation of the reloaded plugin');
        await sleep(600);
        expect(lastOverlay().visible).toBe(true);
        overlay.setSideMenu(true);
        await translationHidden('closed by the side menu');
        // exactly one hide: the unloaded instance didn't send its own
        const hides = overlayUpdates().filter(s => s.visible === false && s.regions);
        expect(hides.length).toBe(1);
    });
});
