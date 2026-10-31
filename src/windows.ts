// Windows port (Decky Loader for Windows).
// On SteamOS gamescope keeps Steam's UI, and with it the translation overlay, above the game. On Windows Big Picture
// is a normal window behind the game, so the backend draws the overlay in a click-through window of its own
// (py_modules/winport/overlay.py). This forwards every ImageState change to it; the screenshot itself stays in the
// backend, which took it.
import { addEventListener, call, removeEventListener, toaster } from '@decky/api';
import { Router } from '@decky/ui';
import { ImageState } from './Overlay';
import type { GameTranslatorLogic } from './Translator';
import { logger } from './Logger';

// The translate/close hotkey (py_modules/winport/hotkey.py HOTKEY)
export const WINDOWS_HOTKEY = 'Ctrl+Alt+T';

type StateListener = Parameters<ImageState['onStateChanged']>[0];

// How often the side menus are checked while a translation is on screen
const SIDE_MENU_CHECK_MS = 250;

export function forwardOverlayToBackend(state: ImageState, dismiss: () => void): () => void {
    let menuTimer: ReturnType<typeof setInterval> | null = null;
    let menuOpen = false;
    const stopWatchingMenus = () => {
        if (menuTimer) clearInterval(menuTimer);
        menuTimer = null;
        menuOpen = false;
    };
    // The side menu over a game is drawn into the game's window, under the overlay window: opening one closes the
    // translation. A menu still open when the translation appears (closing after Translate) doesn't count.
    const watchMenus = () => {
        if (menuTimer) return;
        menuOpen = anySideMenuOpen();
        menuTimer = setInterval(() => {
            const open = anySideMenuOpen();
            const opened = open && !menuOpen;
            menuOpen = open;
            if (opened) dismiss();
        }, SIDE_MENU_CHECK_MS);
    };

    const onChange: StateListener = (
        visible, _imageData, regions, loading, processingStep, processingDetail, processingIsError,
        translationsVisible, fontScale,
    ) => {
        if (visible) watchMenus(); else stopWatchingMenus();
        call('native_overlay_update', {
            visible, regions, loading, processingStep, processingDetail, processingIsError,
            translationsVisible, fontScale,
        }).catch(() => { /* the backend logs its own errors */ });
    };
    state.onStateChanged(onChange);
    return () => {
        stopWatchingMenus();
        state.offStateChanged(onChange);
    };
}

// Ctrl+Alt+T (py_modules/winport/hotkey.py): translate the screen, or dismiss the translation (or the
// translation in progress) when it is up. Windows only gives XInput to the foreground app, so on most setups this
// is the shortcut; a controller button can be mapped to it (OneXConsole, Steam Input).
export function listenForHotkey(logic: GameTranslatorLogic): () => void {
    const onHotkey = () => {
        if (logic.imageState.isVisible()) logic.dismiss();
        else closeAllSideMenus()
            .then(() => logic.takeScreenshotAndTranslate())
            .catch(err => logger.error('Hotkey', 'Translation failed', err));
    };
    addEventListener('translator_hotkey', onHotkey);
    return () => removeEventListener('translator_hotkey', onHotkey);
}

// Problems the backend found while loading (main.py get_boot_status), e.g. a Decky update that changed its Python so
// the capture or overlay modules no longer load: a toast for each, instead of a shortcut that silently does nothing.
export async function showBootProblems(title: string): Promise<void> {
    let problems: string[] = [];
    try {
        problems = await call<[], string[]>('get_boot_status');
    } catch {
        return;  // the backend didn't load at all: Decky shows that itself
    }
    for (const body of problems || []) toaster.toast({ title, body, duration: 10000 });
}

// Problems the backend finds later (main.py emits translator_problem, e.g. the overlay window stopped working): a
// toast each, instead of translations that silently never appear
export function listenForProblems(title: string): () => void {
    const onProblem = (body: string) => toaster.toast({ title, body, duration: 10000 });
    addEventListener('translator_problem', onProblem);
    return () => removeEventListener('translator_problem', onProblem);
}

// Each Steam UI window (Big Picture, the overlay over each game) has a menu store of its own. Steam's internals: the
// methods are still called with ?. and try/catch, so a Steam update that renames them only turns these checks off.
type SideMenuStore = NonNullable<NonNullable<typeof Router.WindowStore>['SteamUIWindows'][number]['MenuStore']>;

function menuStores(): SideMenuStore[] {
    return (Router.WindowStore?.SteamUIWindows || []).map(w => w?.MenuStore).filter(Boolean) as SideMenuStore[];
}

function anySideMenuOpen(stores = menuStores()): boolean {
    return stores.some(s => { try { return !!s.IsAnySideMenuVisible?.(); } catch { return false; } });
}

// Close the side menus before a capture. Router.CloseSideMenus() acts on Big Picture's window only; over a game the
// side panel belongs to the Steam overlay, a window of its own that Steam draws into the game, so it stayed open and
// was captured and translated along with the game. Close them in every window, then wait until none shows a side
// menu, plus the closing animation.
export async function closeAllSideMenus(): Promise<void> {
    // Big Picture's own menu; guarded like the stores below, so a Steam update that renames it doesn't break Translate
    try { Router.CloseSideMenus?.(); } catch { /* the menu stores below still close theirs */ }
    const stores = menuStores();
    let closed = false;
    for (const s of stores) {
        try { if (s.IsAnySideMenuVisible?.()) { s.CloseSideMenus?.(); closed = true; } } catch { /* not a menu window */ }
    }
    if (!closed) return;
    for (let i = 0; i < 20 && anySideMenuOpen(stores); i++) await new Promise(r => setTimeout(r, 50));
    await new Promise(r => setTimeout(r, 300));
}
