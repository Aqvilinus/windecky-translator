// Harness for the end-to-end tests: Steam's UI over its CEF debugger (127.0.0.1:8080, which Decky Loader turns on),
// the screen and keyboard through win32.py, the plugin's log.
//
// A small CDP client of its own instead of Playwright: Playwright's connectOverCDP makes every Steam window opened
// while it is attached wait for it, and a test that hangs or is killed leaves them frozen (it froze the in-game Steam
// overlay once). This one attaches only to the windows it uses, one call at a time, each with a timeout.
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

export const NAME = 'WinDecky Translator';
export const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
export const ARTIFACTS = join(ROOT, 'tests', 'e2e', 'artifacts');
const CDP = 'http://127.0.0.1:8080/json';
const PYTHON = join(ROOT, 'bin', 'python314', 'python', 'python.exe');
const WIN32 = join(ROOT, 'tests', 'e2e', 'win32.py');
const LOG = join(process.env.USERPROFILE || '', 'homebrew', 'logs', 'decky-translator', 'decky-translator.log');
const QUICK_ACCESS_DECKY_TAB = 999;  // @decky/ui QuickAccessTab.Decky

export const sleep = ms => new Promise(r => setTimeout(r, ms));

export async function waitFor(what, fn, timeoutMs = 10000, everyMs = 150) {
    const end = Date.now() + timeoutMs;
    for (;;) {
        const v = await fn();
        if (v) return v;
        if (Date.now() > end) throw new Error(`timed out after ${timeoutMs} ms: ${what}`);
        await sleep(everyMs);
    }
}

// -- screen and keyboard (win32.py)
export function win32(...args) {
    if (!existsSync(PYTHON)) throw new Error(`${PYTHON} missing: the plugin's dependencies are not unpacked in bin/`);
    const r = spawnSync(PYTHON, ['-I', WIN32, ...args.map(String)], { encoding: 'utf8', timeout: 30000 });
    if (r.status !== 0) throw new Error(`win32.py ${args.join(' ')} failed: ${r.stderr || r.stdout}`);
    return JSON.parse(r.stdout.trim().split('\n').pop());
}

export function artifact(name) {
    mkdirSync(ARTIFACTS, { recursive: true });
    return join(ARTIFACTS, name);
}

// -- the plugin's log
export class Log {
    mark() { this.offset = existsSync(LOG) ? statSync(LOG).size : 0; }
    lines() {
        if (!existsSync(LOG)) return [];
        const buf = readFileSync(LOG);
        // after a rotation the file starts over: read it from the start then
        return buf.subarray(buf.length >= this.offset ? this.offset : 0).toString('utf8').split(/\r?\n/).filter(Boolean);
    }
    find(rx) { return this.lines().find(l => rx.test(l)); }
}

// -- CDP: one Steam window
class Target {
    static async open(title) {
        const targets = await (await fetch(CDP)).json();
        const t = typeof title === 'string' ? targets.find(x => x.title === title) : targets.filter(x => title.test(x.title));
        return t;
    }

    constructor(info) { this.info = info; this.id = 0; this.pending = new Map(); }

    async connect() {
        this.ws = new WebSocket(this.info.webSocketDebuggerUrl);
        await new Promise((resolve, reject) => {
            const timer = setTimeout(() => reject(new Error(`CDP connect to ${this.info.title} timed out`)), 5000);
            this.ws.onopen = () => { clearTimeout(timer); resolve(); };
            this.ws.onerror = () => { clearTimeout(timer); reject(new Error(`CDP connect to ${this.info.title} failed`)); };
        });
        this.ws.onmessage = e => {
            const m = JSON.parse(e.data);
            const p = this.pending.get(m.id);
            if (p) { this.pending.delete(m.id); p(m); }
        };
        return this;
    }

    send(method, params = {}, timeoutMs = 15000) {
        const id = ++this.id;
        return new Promise((resolve, reject) => {
            const timer = setTimeout(() => { this.pending.delete(id); reject(new Error(`${method} on ${this.info.title} timed out`)); }, timeoutMs);
            this.pending.set(id, m => {
                clearTimeout(timer);
                if (m.error) reject(new Error(`${method}: ${m.error.message}`)); else resolve(m.result);
            });
            this.ws.send(JSON.stringify({ id, method, params }));
        });
    }

    // fn runs in the page with arg; a returned promise is awaited
    async eval(fn, arg, timeoutMs = 15000) {
        const r = await this.send('Runtime.evaluate', {
            expression: `(${fn})(${JSON.stringify(arg ?? null)})`, awaitPromise: true, returnByValue: true,
        }, timeoutMs);
        if (r.exceptionDetails) throw new Error(`in ${this.info.title}: ${r.exceptionDetails.exception?.description || r.exceptionDetails.text}`);
        return r.result?.value;
    }

    // a real click: mouse events through the browser at the element's centre, like Playwright's click()
    async click(x, y) {
        const at = { x, y, button: 'left', clickCount: 1 };
        await this.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y });
        await this.send('Input.dispatchMouseEvent', { type: 'mousePressed', ...at });
        await this.send('Input.dispatchMouseEvent', { type: 'mouseReleased', ...at });
    }

    close() { try { this.ws?.close(); } catch { /* gone */ } }
}

async function withTarget(info, use) {
    const t = await new Target(info).connect();
    try { return await use(t); } finally { t.close(); }
}

// -- Steam
export class Steam {
    async connect() {
        const info = await Target.open('SharedJSContext');
        if (!info) throw new Error(`Steam's debugger at ${CDP} has no SharedJSContext (is Steam running with Decky Loader?)`);
        this.shared = await new Target(info).connect();
    }

    close() { this.shared?.close(); }

    js(fn, arg, timeoutMs) { return this.shared.eval(fn, arg, timeoutMs); }

    // the plugin instance Decky has registered, and the one its side menu shows
    pluginState() {
        return this.js(name => {
            const ds = DeckyPluginLoader.deckyState;
            const reg = ds._plugins.find(p => p.name === name);
            const logic = reg?.content?.props?.logic;
            return {
                loaded: !!reg,
                visible: !!logic?.imageState?.isVisible(),
                loading: !!logic?.imageState?.isLoading(),
                activeName: ds._activePlugin?.name ?? null,
                activeIsRegistered: ds._activePlugin === reg,
            };
        }, NAME);
    }

    dismiss() {
        return this.js(name => {
            DeckyPluginLoader.deckyState._plugins.find(p => p.name === name)?.content?.props?.logic?.dismiss();
            return true;
        }, NAME);
    }

    sideMenuOpen() {
        return this.js(() => (DFL.Router.WindowStore?.SteamUIWindows || []).some(w => {
            try { return !!w?.MenuStore?.IsAnySideMenuVisible?.(); } catch { return false; }
        }));
    }

    // Steam's own "open the Quick Access menu" (what its button calls) on the Decky tab with the plugin open, in the
    // window the user is looking at: the game's Steam overlay while a game runs (Navigation.OpenQuickAccessMenu would
    // open it in Big Picture, behind the game), Big Picture otherwise
    async openPluginInSideMenu() {
        await this.js(({ name, tab }) => {
            DeckyPluginLoader.deckyState.setActivePlugin(name);
            const windows = DFL.Router.WindowStore.SteamUIWindows;
            const w = windows.find(w => w.m_eWindowType === 1) || windows[0];  // 1: a game's overlay
            w.MenuStore.OpenQuickAccessMenu(tab);
            return true;
        }, { name: NAME, tab: QUICK_ACCESS_DECKY_TAB });
        return waitFor('the plugin button in the side menu', () => this.pluginButton(), 10000, 300);
    }

    closeSideMenus() {
        return this.js(() => {
            for (const w of DFL.Router.WindowStore.SteamUIWindows) w.MenuStore.CloseSideMenus();
            return true;
        });
    }

    // the backend has Ctrl+Alt+T registered
    async hotkeyRegistered() {
        const s = await this.js(name => DeckyBackend.call('loader/call_plugin_method', name, 'get_windows_status'), NAME);
        return !!s?.hotkey?.registered;
    }

    // the Translate / Close Overlay button in an open Quick Access window: its text and a click() on it
    async pluginButton() {
        const windows = await Target.open(/^QuickAccess_/);
        for (const info of windows) {
            const found = await withTarget(info, t => t.eval(() => {
                if (!document.hasFocus()) return null;  // the open one; a closed side menu keeps its page
                const b = [...document.querySelectorAll('button')]
                    .find(e => /^\s*(Translate|Close Overlay|Download required)\s*$/.test(e.textContent || ''));
                const r = b?.getBoundingClientRect();
                if (!r || !r.width || !r.height) return null;
                return { text: b.textContent.trim(), x: r.left + r.width / 2, y: r.top + r.height / 2 };
            }).catch(() => null));
            if (found) return { ...found, window: info.title, click: () => withTarget(info, t => t.click(found.x, found.y)) };
        }
        return null;
    }

    async reloadPlugin() {
        await this.js(name => DeckyBackend.call('utilities/disable_plugin', name).then(() => true), NAME, 30000);
        await sleep(2000);
        await this.js(name => DeckyBackend.call('utilities/enable_plugin', name).then(() => true), NAME, 30000);
    }

    runningApp(appid) {
        return this.js(id => (DFL.Router.RunningApps || []).some(a => String(a.appid) === String(id)), appid);
    }

    runGame(appid) { return this.js(id => { SteamClient.Apps.RunGame(String(id), '', -1, 100); return true; }, appid); }

    terminateGame(appid) { return this.js(id => { SteamClient.Apps.TerminateApp(String(id), false); return true; }, appid); }
}
