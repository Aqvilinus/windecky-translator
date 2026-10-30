// @vitest-environment happy-dom
// Both real halves: the plugin bundle in the emulated Steam + Decky, calling the real main.py (pythonBackend.ts;
// capture, overlay window, hotkey and network stubbed on the Python side). Catches what each half's own tests can't:
// a call whose arguments or result the other side reads differently. Runs when PLUGIN_PYTHON is set (CI does).
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { PYTHON, PythonBackend } from './pythonBackend';
import { GAME, Session, sleep, waitFor } from './session';

describe.skipIf(!PYTHON)('frontend with the real backend', () => {
    let backend: PythonBackend;
    let session: Session;

    beforeAll(async () => {
        backend = await new PythonBackend().start();
        session = await Session.start(backend);
    }, 60000);

    afterAll(() => {
        session?.stop();
        backend?.stop();
    });

    afterEach(() => {
        expect(backend.errors, `backend calls that failed\n${backend.stderr.slice(-3000)}`).toEqual([]);
    });

    it('loads with the backend\'s settings', async () => {
        const settings = await waitFor('get_all_settings', () => session.callsOf('get_all_settings').length);
        expect(settings).toBeGreaterThan(0);
        await waitFor('the startup overlay update', () => session.overlayUpdates().length);
    });

    it('Translate in the side menu over a game: capture, OCR and translation in main.py, drawn by its overlay window', async () => {
        const overlay = session.steam.launchGame(GAME.appid, GAME.name);
        (await session.openPluginInSideMenu(overlay)).click();
        const shown = await session.translationShown('the translation', 0, 10000);
        expect(shown.regions.map((r: any) => r.translatedText)).toEqual(['Welcome, traveller', 'New game']);

        const win = await backend.windows();
        expect(win.captures).toBe(1);
        expect(win.overlay?.visible).toBe(true);
        expect(win.overlay?.regions?.map(r => r.translatedText)).toEqual(['Welcome, traveller', 'New game']);
        expect(win.hotkey?.holds.at(-1)).toEqual([true, 'overlay']);

        overlay.setSideMenu(true);  // the side menu closes it, in the backend's window too
        await session.translationHidden('the translation closed by the side menu');
        await waitFor('the overlay window to hide', async () => (await backend.windows()).overlay?.visible === false);
    });

    it('switching the plugin off reaches the hotkey', async () => {
        const overlay = session.steam.windows[1];
        await session.openPluginInSideMenu(overlay);
        overlay.element.querySelector<HTMLInputElement>('[data-label="Plugin is enabled"] input')!.click();
        await waitFor('the hotkey to be switched off', async () => (await backend.windows()).hotkey?.enabled === false);
        overlay.element.querySelector<HTMLInputElement>('[data-label="Plugin is disabled"] input')!.click();
        await waitFor('the hotkey to be switched on', async () => (await backend.windows()).hotkey?.enabled === true);
        overlay.setSideMenu(false);
    });

    it('after a plugin reload (backend restarted too) Translate still works', async () => {
        const overlay = session.steam.windows[1];
        await session.openPluginInSideMenu(overlay);
        await session.decky.loadPlugin();
        await waitFor('Decky to show the new instance', () => session.decky.state._activePlugin === session.decky.plugin, 2000);
        await session.sideMenuShowsCurrentPlugin(overlay);
        overlay.setSideMenu(false);
        const translate = await session.openPluginInSideMenu(overlay);
        const since = session.overlayUpdates().length;
        translate.click();
        await session.translationShown('the translation after the reload', since, 10000);  // a cold restart of main.py
        await sleep(300);
        expect((await backend.windows()).overlay?.visible).toBe(true);
    });
});
