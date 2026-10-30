// Steam's SharedJSContext, emulated: what the plugin bundle (dist/index.js) finds there. Rollup turns the plugin's
// imports into globals (@decky/rollup: react -> SP_REACT, react-dom -> SP_REACTDOM, @decky/ui -> DFL), so this
// installs React itself, a DFL with plain-HTML stand-ins for Steam's components, Router with a menu store per Steam
// UI window, and the SteamClient calls the plugin uses.
//
// The behaviour that matters for the plugin is Steam's, as found on the device:
// - Each Steam UI window (Big Picture, the overlay over each game) has a MenuStore of its own; the side menu over a
//   game lives in the game's overlay window.
// - Router.CloseSideMenus() acts on Big Picture's window only.
import * as React from 'react';
import * as ReactDOM from 'react-dom';
import { createRoot, type Root } from 'react-dom/client';

const h = React.createElement;

export interface RunningApp { appid: string; display_name: string }

// One Steam UI window with its side menu (the Quick Access Menu, where Decky's plugins live)
export class SteamWindow {
    readonly element: HTMLElement;
    private sideMenuOpen = false;
    private root: Root | null = null;
    onSideMenu: ((open: boolean) => void) | null = null;
    // how long the side menu takes to close (Steam animates it; IsAnySideMenuVisible is true meanwhile)
    closeDelayMs = 0;

    constructor(readonly name: string, private readonly renderQam: () => React.ReactNode) {
        this.element = document.createElement('div');
        this.element.dataset.steamWindow = name;
        this.element.hidden = true;
        document.body.appendChild(this.element);
    }

    readonly MenuStore = {
        IsAnySideMenuVisible: () => this.sideMenuOpen,
        CloseSideMenus: () => {
            if (this.closeDelayMs) setTimeout(() => this.setSideMenu(false), this.closeDelayMs);
            else this.setSideMenu(false);
        },
        OpenQuickAccessMenu: () => this.setSideMenu(true),
    };

    get isSideMenuOpen() { return this.sideMenuOpen; }

    // Steam keeps the Quick Access Menu's tree mounted while the menu is closed, so the plugin's state survives
    setSideMenu(open: boolean) {
        this.sideMenuOpen = open;
        this.element.hidden = !open;
        if (open && !this.root) {
            this.root = createRoot(this.element);
            this.root.render(this.renderQam());
        }
        this.onSideMenu?.(open);
    }

    unmount() {
        this.root?.unmount();
        this.root = null;
        this.element.remove();
    }
}

type Listener<T> = (arg: T) => void;

function registry<T>() {
    const listeners = new Set<Listener<T>>();
    return {
        register(cb: Listener<T>) {
            listeners.add(cb);
            return { unregister: () => listeners.delete(cb) };
        },
        fire(arg: T) { for (const cb of [...listeners]) cb(arg); },
        get count() { return listeners.size; },
    };
}

export interface AppLifetimeNotification { unAppID: number; nInstanceID: number; bRunning: boolean }

export class FakeSteam {
    readonly windows: SteamWindow[] = [];
    readonly runningApps: RunningApp[] = [];
    readonly appLifetime = registry<AppLifetimeNotification>();
    readonly suspend = registry<unknown>();
    readonly modals: HTMLElement[] = [];
    private modalRoots: Root[] = [];

    constructor(renderQam: () => React.ReactNode) {
        this.windows.push(new SteamWindow('Big Picture', renderQam));
        this.renderQam = renderQam;
    }
    private readonly renderQam: () => React.ReactNode;

    get bigPicture() { return this.windows[0]; }

    // A game starts: Steam reports it, and opens its overlay window (where the side menu over the game lives)
    launchGame(appid: string, name: string): SteamWindow {
        this.runningApps.push({ appid, display_name: name });
        const w = new SteamWindow(`Overlay ${appid}`, this.renderQam);
        this.windows.push(w);
        this.appLifetime.fire({ unAppID: Number(appid), nInstanceID: 1, bRunning: true });
        return w;
    }

    readonly Router = {
        get MainRunningApp() { return steam().runningApps[0]; },
        get RunningApps() { return steam().runningApps; },
        WindowStore: { get SteamUIWindows() { return steam().windows; } },
        CloseSideMenus: () => this.bigPicture.MenuStore.CloseSideMenus(),
        Navigate: () => { /* no routes in the tests */ },
        NavigateBackOrOpenMenu: () => { /* not used */ },
    };

    readonly SteamClient = {
        GameSessions: { RegisterForAppLifetimeNotifications: (cb: Listener<AppLifetimeNotification>) => this.appLifetime.register(cb) },
        User: { RegisterForPrepareForSystemSuspendProgress: (cb: Listener<unknown>) => this.suspend.register(cb) },
        Apps: {},
        System: {},
    };

    showModal(modal: React.ReactNode): { Close(): void; Update(m: React.ReactNode): void } {
        const el = document.createElement('div');
        el.dataset.modal = String(this.modals.length);
        document.body.appendChild(el);
        const root = createRoot(el);
        const close = () => { root.unmount(); el.remove(); this.modals.splice(this.modals.indexOf(el), 1); };
        const withClose = (m: React.ReactNode) =>
            React.isValidElement(m) ? React.cloneElement(m as React.ReactElement<{ closeModal?: () => void }>, { closeModal: close }) : m;
        root.render(withClose(modal));
        this.modals.push(el);
        this.modalRoots.push(root);
        return { Close: close, Update: m => root.render(withClose(m)) };
    }

    teardown() {
        for (const w of this.windows) w.unmount();
        for (const r of this.modalRoots) r.unmount();
        for (const el of this.modals) el.remove();
    }
}

let current: FakeSteam | null = null;
const steam = () => {
    if (!current) throw new Error('no emulated Steam running');
    return current;
};

// ---------------------------------------------------------------- @decky/ui (DFL) stand-ins
// Plain HTML with the props the plugin passes: buttons are <button>, toggles are checkboxes, dropdowns are <select>,
// so tests find and use them like a user would.
type AnyProps = Record<string, any>;

const Row = (cls: string, p: AnyProps, ...control: React.ReactNode[]) =>
    h('div', { className: cls, 'data-label': typeof p.label === 'string' ? p.label : undefined },
        p.label != null && h('label', null, p.label), ...control,
        p.description != null && h('div', { className: 'description' }, p.description));

const ButtonItem = (p: AnyProps) =>
    Row('ButtonItem', p, h('button', { onClick: p.onClick, disabled: p.disabled }, p.children));
const DialogButton = (p: AnyProps) => h('button', { onClick: p.onClick, disabled: p.disabled, style: p.style }, p.children);
const ToggleField = (p: AnyProps) =>
    Row('ToggleField', p, h('input', {
        type: 'checkbox', checked: !!p.checked, disabled: p.disabled,
        onChange: (e: any) => p.onChange?.(e.target.checked),
    }));
const SliderField = (p: AnyProps) =>
    Row('SliderField', p, h('input', {
        type: 'range', min: p.min, max: p.max, step: p.step, value: p.value, disabled: p.disabled,
        onChange: (e: any) => p.onChange?.(Number(e.target.value)),
    }));
const Dropdown = (p: AnyProps) => {
    const options: AnyProps[] = p.rgOptions || [];
    const index = options.findIndex(o => o.data === p.selectedOption);
    return h('select', {
        value: String(index), disabled: p.disabled,
        onChange: (e: any) => p.onChange?.(options[Number(e.target.value)]),
    }, options.map((o, i) => h('option', { key: i, value: String(i) }, typeof o.label === 'string' ? o.label : String(o.data))));
};
const DropdownItem = (p: AnyProps) => Row('DropdownItem', p, h(Dropdown, p));
const TextField = (p: AnyProps) =>
    Row('TextField', p, h('input', { type: p.bIsPassword ? 'password' : 'text', value: p.value ?? '', onChange: p.onChange, disabled: p.disabled }));
const Field = (p: AnyProps) => Row('Field', p, p.children);
const Focusable = ({ children, onActivate, onOKButton, flow, focusWithinClassName, noFocusRing, ...rest }: AnyProps) =>
    h('div', { ...rest, onClick: rest.onClick ?? onActivate }, children);
const PanelSection = (p: AnyProps) => h('section', { className: 'PanelSection' }, p.title && h('h2', null, p.title), p.children);
const PanelSectionRow = (p: AnyProps) => h('div', { className: 'PanelSectionRow' }, p.children);
const ModalRoot = (p: AnyProps) => h('div', { role: 'dialog' }, p.children,
    h('button', { onClick: () => { p.onCancel?.(); p.closeModal?.(); } }, 'Close dialog'));
const Tabs = (p: AnyProps) => {
    const tabs: AnyProps[] = p.tabs || [];
    const active = tabs.find(t => t.id === p.activeTab) ?? tabs[0];
    return h('div', { className: 'Tabs' },
        h('div', { role: 'tablist' }, tabs.map(t => h('button', {
            key: t.id, role: 'tab', 'data-tab': t.id, 'aria-selected': t === active, onClick: () => p.onShowTab?.(t.id),
        }, t.title))),
        h('div', { role: 'tabpanel', 'data-tab': active?.id }, active?.content));
};

// Steam's webpack modules, as findModuleChild walks them: the plugin looks for the hook that asks Steam to compose
// its UI above the game (Overlay.tsx, ActivationIndicator.tsx)
const steamModules: object[] = [{
    useUIComposition(_level: number) {
        // AddMinimumCompositionStateRequest ChangeMinimumCompositionStateRequest RemoveMinimumCompositionStateRequest
    },
}];

function makeDFL(s: FakeSteam) {
    return {
        ButtonItem, DialogButton, ToggleField, SliderField, Dropdown, DropdownItem, TextField, Field, Focusable,
        PanelSection, PanelSectionRow, ModalRoot, Tabs,
        Router: s.Router,
        Navigation: { Navigate: () => {}, NavigateBack: () => {}, CloseSideMenus: s.Router.CloseSideMenus },
        staticClasses: new Proxy({}, { get: (_t, k) => `staticClasses-${String(k)}` }),
        findModuleChild: (filter: (m: any) => any) => {
            for (const m of steamModules) { const r = filter(m); if (r) return r; }
            return undefined;
        },
        getGamepadNavigationTrees: () => [],
        showModal: (modal: React.ReactNode) => s.showModal(modal),
    };
}

// Steam on Windows (the user agent the plugin checks for its Windows port)
const STEAM_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.6478.183 Safari/537.36 Valve Steam Client';

export function setGlobal(name: string, value: unknown) {
    (globalThis as any)[name] = value;
    if (typeof window !== 'undefined' && (window as any) !== globalThis) (window as any)[name] = value;
}

export function startSteam(renderQam: () => React.ReactNode): FakeSteam {
    if (current) throw new Error('emulated Steam already running');
    const s = new FakeSteam(renderQam);
    current = s;
    Object.defineProperty(navigator, 'userAgent', { value: STEAM_UA, configurable: true });
    setGlobal('SP_REACT', React);
    setGlobal('SP_REACTDOM', ReactDOM);
    setGlobal('DFL', makeDFL(s));
    setGlobal('SteamClient', s.SteamClient);
    return s;
}

export function stopSteam() {
    current?.teardown();
    current = null;
}
