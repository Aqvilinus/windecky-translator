// End-to-end tests on the real device: Steam Big Picture + Decky Loader running, a real Steam game, the real
// translate shortcut, the real button in Steam's side menu, and what actually ends up on screen.
//
// The final smoke check before a release. The logic is tested in CI (tests/README.md); what only this checks:
// the real Steam and Decky behave as the emulator in tests/integration assumes (menu stores per window, Decky
// keeping the unloaded plugin in the side menu), and the Windows parts CI replaces really work: RegisterHotKey
// with a game in front, the WGC capture of the game, the on-device OCR, the overlay window drawn over the game.
//
//   pnpm test:e2e                     (E2E_APPID / E2E_WINDOW pick another game, default The Banner Saga)
//
// The tests take over the screen and keyboard for about a minute: don't use the device meanwhile. They launch the
// game if it isn't running (and close it afterwards), translate it, and leave the plugin as they found it.
// Screenshots of each translation land in tests/e2e/artifacts/.
import assert from 'node:assert/strict';
import { after, before, describe, it } from 'node:test';
import { Log, NAME, Steam, artifact, sleep, waitFor, win32 } from './harness.mjs';

const APPID = process.env.E2E_APPID || '237990';
const WINDOW = process.env.E2E_WINDOW || 'Banner Saga';

const steam = new Steam();
const log = new Log();
let launchedGame = false;

const overlay = () => win32('state', WINDOW).overlay;
const game = () => win32('state', WINDOW).target;

async function focusGame() {
    const r = win32('focus', WINDOW);
    assert.ok(r.ok, `could not bring the game to the front: ${r.error}`);
    await waitFor('Ctrl+Alt+T registered with the game in front', () => steam.hotkeyRegistered(), 5000, 200);
}

async function expectOverlay(visible, what, timeoutMs) {
    await waitFor(`${what}: overlay window ${visible ? 'shown' : 'hidden'}`, () => overlay()?.visible === visible, timeoutMs);
}

// a translation finished since log.mark(): OCR found text and the translation step completed
async function expectTranslationInLog() {
    await waitFor('"Translation completed" in the plugin log', () => log.find(/Translation completed in/), 30000, 300);
    const ocr = log.find(/OCR completed in .* found (\d+) regions/);
    assert.ok(ocr, 'no OCR line in the log');
    assert.ok(Number(/found (\d+) regions/.exec(ocr)[1]) > 0, `OCR found no text: ${ocr}`);
}

// the overlay covers the game and really drew something over it
async function expectTranslationOnScreen(name, before) {
    const g = game(), o = overlay();
    assert.ok(g && o, 'game or overlay window missing');
    assert.deepEqual(o.rect.slice(2), g.rect.slice(2).map(v => v), 'overlay is not the size of the game window');
    await sleep(700);  // the label pass
    const shot = artifact(`${name}.png`);
    win32('grab', ...o.rect, shot);
    if (before) {
        const { mean } = win32('diff', before, shot);
        assert.ok(mean > 1, `the screen barely changed (mean pixel difference ${mean}): no labels drawn?`);
    }
    const st = await steam.pluginState();
    assert.ok(st.visible && !st.loading, `frontend state after translating: ${JSON.stringify(st)}`);
}

function screenshotGame(name) {
    const g = game();
    const path = artifact(`${name}.png`);
    win32('grab', ...g.rect, path);
    return path;
}

async function dismissIfShown() {
    if (overlay()?.visible || (await steam.pluginState()).visible) {
        await steam.dismiss();
        await expectOverlay(false, 'cleanup', 3000);
    }
}

describe(`${NAME} end to end`, { timeout: 240000 }, () => {
    before(async () => {
        await steam.connect();
        const st = await steam.pluginState();
        assert.ok(st.loaded, `${NAME} is not loaded in Decky Loader`);
        if (!await steam.runningApp(APPID)) {
            await steam.runGame(APPID);
            launchedGame = true;
        }
        await waitFor(`the game window (${WINDOW})`, () => game(), 90000, 1000);
        await sleep(launchedGame ? 8000 : 0);  // past the splash screens
        await steam.closeSideMenus();
        await dismissIfShown();
    });

    after(async () => {
        try {
            await steam.closeSideMenus();
            await dismissIfShown();
            if (launchedGame) await steam.terminateGame(APPID);
        } finally {
            steam.close();
        }
    });

    // device only: RegisterHotKey + SendInput, WGC capture, on-device OCR, the layered window over the game
    it('Ctrl+Alt+T translates the game and closes the translation again', async () => {
        await focusGame();
        const before = screenshotGame('hotkey-before');
        log.mark();
        win32('keys', 'ctrl+alt+t');
        await expectOverlay(true, 'after Ctrl+Alt+T', 15000);
        await expectTranslationInLog();
        await expectTranslationOnScreen('hotkey-translated', before);

        win32('keys', 'ctrl+alt+t');
        await expectOverlay(false, 'after the second Ctrl+Alt+T', 3000);
        assert.equal((await steam.pluginState()).visible, false);
    });

    // device only: Steam's real menu store of the game's overlay window reports the side menu
    it('opening the Steam side menu closes the translation, and the menu offers Translate', async () => {
        await focusGame();
        log.mark();
        win32('keys', 'ctrl+alt+t');
        await expectOverlay(true, 'after Ctrl+Alt+T', 15000);
        await expectTranslationInLog();

        const { text } = await steam.openPluginInSideMenu();
        await expectOverlay(false, 'with the side menu open', 3000);
        assert.equal((await steam.pluginState()).visible, false, 'the frontend still has a translation up');
        assert.equal(text, 'Translate', 'the side menu button');

        await steam.closeSideMenus();
        await sleep(1500);
        assert.equal(overlay().visible, false, 'the translation came back after the menu closed');
    });

    // device only: the button in Steam's real Quick Access window, and the side menu gone from the capture
    it('the Translate button in the side menu translates the game', async () => {
        await focusGame();
        const before = screenshotGame('button-before');
        const menuButton = await steam.openPluginInSideMenu();
        const { text } = menuButton;
        assert.equal(text, 'Translate');
        log.mark();
        await menuButton.click();
        await waitFor('the side menu to close', async () => !await steam.sideMenuOpen(), 5000);
        await expectOverlay(true, 'after Translate in the side menu', 15000);
        await expectTranslationInLog();
        await expectTranslationOnScreen('button-translated', before);
        await dismissIfShown();
    });

    // device only: real Decky Loader's reload (the behaviour tests/integration/decky.ts emulates)
    it('after a plugin reload (store update) the side menu still translates', async () => {
        // the side menu was open on the plugin when it was reloaded: Decky kept showing the unloaded instance
        await steam.openPluginInSideMenu();
        log.mark();
        await steam.reloadPlugin();
        await waitFor('the backend to restart', () => log.find(/ Decky Translator v\S+ starting/), 30000, 300);
        await waitFor('Decky to register the reloaded plugin', async () => (await steam.pluginState()).loaded, 15000);
        await sleep(1000);
        const st = await steam.pluginState();
        assert.ok(st.activeName !== NAME || st.activeIsRegistered, 'the side menu shows the unloaded instance');

        await steam.closeSideMenus();
        await focusGame();
        const before = screenshotGame('reload-before');
        const menuButton = await steam.openPluginInSideMenu();
        const { text } = menuButton;
        assert.equal(text, 'Translate', 'the side menu button after the reload');
        log.mark();
        await menuButton.click();
        await expectOverlay(true, 'after Translate in the side menu (reloaded plugin)', 15000);
        await expectTranslationInLog();
        await expectTranslationOnScreen('reload-translated', before);
        await dismissIfShown();
    });
});
