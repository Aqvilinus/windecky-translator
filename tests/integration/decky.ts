// Decky Loader's frontend, emulated: the API @decky/api connects to, the plugin list in the side menu, and loading
// and reloading the real plugin bundle (dist/index.js) the way Decky's plugin loader does.
//
// The parts that matter for the plugin follow decky-loader's frontend (src/plugin-loader.tsx, components/DeckyState):
// - The plugin entry is a copy of what the plugin's definePlugin returned, plus name and version.
// - A reload calls the old instance's onDismount, drops it from the list, imports the bundle again and registers
//   the new instance. deckyState._activePlugin (the plugin open in the side menu) is NOT updated: it keeps pointing
//   at the unloaded instance's entry, so the side menu goes on showing that one unless something calls
//   setActivePlugin again (src/deckyState.ts does).
import { readFileSync } from 'node:fs';
import * as React from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { setGlobal } from './steam';

const h = React.createElement;

export interface PluginEntry {
    name: string;
    version: string;
    title?: React.ReactNode;
    titleView?: React.ReactNode;
    content?: React.ReactElement;
    icon?: React.ReactNode;
    alwaysRender?: boolean;
    onDismount?(): void;
}

export interface Backend {
    call(method: string, args: unknown[]): Promise<unknown>;
    // Decky restarts the plugin's backend process when it reloads the plugin
    restart?(): Promise<void>;
}

export interface Call { method: string; args: any[] }

class DeckyState {
    _plugins: PluginEntry[] = [];
    _activePlugin: PluginEntry | null = null;
    private listeners = new Set<() => void>();

    setPlugins(plugins: PluginEntry[]) { this._plugins = plugins; this.notify(); }
    setActivePlugin(name: string) { this._activePlugin = this._plugins.find(p => p.name === name) ?? null; this.notify(); }
    closeActivePlugin() { this._activePlugin = null; this.notify(); }
    subscribe(cb: () => void) { this.listeners.add(cb); return () => { this.listeners.delete(cb); }; }
    private notify() { for (const cb of [...this.listeners]) cb(); }
}

function useDeckyState(state: DeckyState) {
    const [, update] = React.useReducer((n: number) => n + 1, 0);
    React.useEffect(() => state.subscribe(update), [state]);
    return state;
}

// Decky's tab in the side menu: the open plugin, or the list of plugins
function DeckyPanel({ state }: { state: DeckyState }) {
    useDeckyState(state);
    const active = state._activePlugin;
    if (active) {
        return h('div', { 'data-decky-plugin': active.name },
            h('button', { 'data-decky-back': true, onClick: () => state.closeActivePlugin() }, 'Back'),
            h('div', { className: 'titleView' }, active.titleView ?? active.title),
            active.content);
    }
    return h('ul', { 'data-decky-plugins': true },
        state._plugins.map(p => h('li', { key: p.name },
            h('button', { onClick: () => state.setActivePlugin(p.name) }, p.name))));
}

// Global components (routerHook.addGlobalComponent) are drawn in Big Picture's window, outside the side menu
function GlobalComponents({ decky }: { decky: FakeDecky }) {
    const [, update] = React.useReducer((n: number) => n + 1, 0);
    React.useEffect(() => { decky.onGlobalsChanged = update; return () => { decky.onGlobalsChanged = null; }; }, [decky]);
    return h(React.Fragment, null, [...decky.globalComponents].map(([name, C]) => h(C, { key: name })));
}

// The bundle is an ES module whose only import-free export is the default (rollup output, `export { x as default }`);
// Decky imports it with a cache-busting query, so each load is a fresh instance. Here it is evaluated as a function
// body in the global scope, where its globals (DFL, SP_REACT, SteamClient...) are.
function evaluateBundle(path: string, load: number): () => Omit<PluginEntry, 'version'> {
    const code = readFileSync(path, 'utf8');
    const exp = /export\s*\{\s*([\w$]+)\s+as\s+default\s*\};?/.exec(code);
    if (!exp) throw new Error(`${path}: no default export found`);
    const body = code.replace(exp[0], `return ${exp[1]};`) + `\n//# sourceURL=decky-plugin-load-${load}.js`;
    return new Function(body)();
}

const API_INIT = '__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit';

export class FakeDecky {
    readonly state = new DeckyState();
    readonly calls: Call[] = [];
    readonly toasts: unknown[] = [];
    readonly globalComponents = new Map<string, React.ComponentType>();
    onGlobalsChanged: (() => void) | null = null;
    private listeners = new Map<string, Set<(...args: any[]) => void>>();
    private loads = 0;
    private globalsRoot: Root | null = null;

    constructor(readonly backend: Backend, readonly bundlePath: string, readonly pluginName: string, readonly version = 'test') {
        setGlobal('DeckyPluginLoader', { deckyState: this.state });
        setGlobal(API_INIT, { connect: (_version: number, name: string) => this.api(name) });
    }

    // What Decky renders into each window's side menu
    readonly renderSideMenu = () => h(DeckyPanel, { state: this.state });

    private api(_pluginName: string) {
        const notEmulated = (what: string) => () => { throw new Error(`${what} is not emulated`); };
        const call = async (method: string, ...args: any[]) => {
            this.calls.push({ method, args });
            return this.backend.call(method, args);
        };
        return {
            _version: 2,
            call,
            callable: (method: string) => (...args: any[]) => call(method, ...args),
            addEventListener: (event: string, cb: (...args: any[]) => void) => {
                if (!this.listeners.has(event)) this.listeners.set(event, new Set());
                this.listeners.get(event)!.add(cb);
                return cb;
            },
            removeEventListener: (event: string, cb: (...args: any[]) => void) => { this.listeners.get(event)?.delete(cb); },
            routerHook: {
                addGlobalComponent: (name: string, c: React.ComponentType) => { this.globalComponents.set(name, c); this.onGlobalsChanged?.(); },
                removeGlobalComponent: (name: string) => { this.globalComponents.delete(name); this.onGlobalsChanged?.(); },
                addRoute: () => {}, removeRoute: () => {}, addPatch: () => {}, removePatch: () => {},
            },
            toaster: { toast: (t: unknown) => { this.toasts.push(t); } },
            useQuickAccessVisible: () => true,
            openFilePicker: notEmulated('openFilePicker'),
            executeInTab: notEmulated('executeInTab'),
            injectCssIntoTab: notEmulated('injectCssIntoTab'),
            removeCssFromTab: notEmulated('removeCssFromTab'),
            fetchNoCors: notEmulated('fetchNoCors'),
            getExternalResourceURL: (url: string) => url,
        };
    }

    // An event from the plugin's backend (decky.emit in main.py)
    emit(event: string, ...args: unknown[]) {
        for (const cb of [...(this.listeners.get(event) ?? [])]) cb(...args);
    }

    listenerCount(event: string) { return this.listeners.get(event)?.size ?? 0; }

    get plugin(): PluginEntry | undefined { return this.state._plugins.find(p => p.name === this.pluginName); }

    // Load (or reload) the plugin, as plugin-loader.tsx importPlugin does
    async loadPlugin() {
        if (!this.globalsRoot) {
            const el = document.createElement('div');
            el.dataset.globalComponents = '';
            document.body.appendChild(el);
            this.globalsRoot = createRoot(el);
            this.globalsRoot.render(h(GlobalComponents, { decky: this }));
        }
        const old = this.plugin;
        if (old) {
            old.onDismount?.();
            this.state._plugins = this.state._plugins.filter(p => p !== old);
            await this.backend.restart?.();
        }
        const plugin = evaluateBundle(this.bundlePath, ++this.loads)();
        this.state.setPlugins([...this.state._plugins, { ...plugin, name: this.pluginName, version: this.version }]);
    }

    unload() {
        this.plugin?.onDismount?.();
        this.state.setPlugins(this.state._plugins.filter(p => p.name !== this.pluginName));
        this.globalsRoot?.unmount();
        this.globalsRoot = null;
    }
}
