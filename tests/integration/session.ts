// One emulated Steam + Decky Loader with the plugin loaded, and what the tests do in it like a user would.
import { BUNDLE } from './buildPlugin';
import { FakeDecky, type Backend } from './decky';
import { startSteam, stopSteam, type FakeSteam, type SteamWindow } from './steam';

export const NAME = 'WinDecky Translator';
export const GAME = { appid: '237990', name: 'The Banner Saga' };

export async function waitFor<T>(what: string, check: () => T | undefined | null | false | Promise<T | undefined | null | false>,
    timeoutMs = 3000): Promise<T> {
    const end = Date.now() + timeoutMs;
    for (;;) {
        const r = await check();
        if (r) return r;
        if (Date.now() > end) throw new Error(`timed out waiting for ${what}`);
        await new Promise(res => setTimeout(res, 20));
    }
}

export const sleep = (ms: number) => new Promise(res => setTimeout(res, ms));

export function buttons(win: SteamWindow, text: string): HTMLButtonElement[] {
    return [...win.element.querySelectorAll('button')].filter(b => b.textContent?.trim() === text);
}

export class Session {
    readonly steam: FakeSteam;
    readonly decky: FakeDecky;

    constructor(readonly backend: Backend) {
        this.steam = startSteam(() => this.decky.renderSideMenu());
        this.decky = new FakeDecky(backend, BUNDLE, NAME);
    }

    static async start(backend: Backend) {
        const s = new Session(backend);
        await s.decky.loadPlugin();
        return s;
    }

    stop() {
        this.decky.unload();
        stopSteam();
        document.body.innerHTML = '';
    }

    // native_overlay_update: what the backend's overlay window was told to draw
    overlayUpdates = () => this.decky.calls.filter(c => c.method === 'native_overlay_update').map(c => c.args[0]);
    lastOverlay = () => this.overlayUpdates().at(-1);
    callsOf = (method: string) => this.decky.calls.filter(c => c.method === method);

    // The plugin's main button in that window's side menu ("Translate" / "Close Overlay")
    mainButton = (win: SteamWindow) => waitFor(`the plugin's button in ${win.name}`,
        () => win.isSideMenuOpen && (buttons(win, 'Translate')[0] ?? buttons(win, 'Close Overlay')[0]));

    // Open the side menu in a window, on the plugin (Decky's list, then the plugin)
    async openPluginInSideMenu(win: SteamWindow) {
        win.setSideMenu(true);
        const entry = await waitFor('the plugin in the side menu', () =>
            win.element.querySelector('[data-decky-plugin]') || buttons(win, NAME)[0]);
        if (entry instanceof HTMLButtonElement) entry.click();
        return this.mainButton(win);
    }

    // The side menu in that window shows the plugin's current instance (React has rendered it), e.g. after a reload
    sideMenuShowsCurrentPlugin = (win: SteamWindow) => waitFor(`${win.name}'s side menu to show the current instance`,
        () => win.element.querySelector(`[data-decky-plugin][data-decky-load="${this.decky.plugin?.loadId}"]`), 2000);

    // A translation is on screen: the overlay window was sent the translated regions (since the given update)
    translationShown = (what: string, since = 0, timeoutMs = 5000) => waitFor(what, () =>
        this.overlayUpdates().slice(since).filter(s => s.visible && !s.loading && s.regions?.length).at(-1), timeoutMs);

    translationHidden = (what: string) => waitFor(what, () => this.lastOverlay()?.visible === false && this.lastOverlay());
}
