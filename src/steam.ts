// Where the plugin reaches into Steam's internals, which have no public API for these: the side menus and the window
// a dialog opens in. Each is guarded, so a Steam update that renames something only turns that part off.
import { Router, getGamepadNavigationTrees, showModal as deckyShowModal } from '@decky/ui';

const SIDE_MENU_CLOSE_ANIMATION_MS = 300;

// Each Steam UI window (Big Picture, the overlay over each game) has a menu store of its own. Steam's internals: the
// methods are still called with ?. and try/catch, so a Steam update that renames them only turns these checks off.
type SideMenuStore = NonNullable<NonNullable<typeof Router.WindowStore>['SteamUIWindows'][number]['MenuStore']>;

function menuStores(): SideMenuStore[] {
    return (Router.WindowStore?.SteamUIWindows || []).map(w => w?.MenuStore).filter(Boolean) as SideMenuStore[];
}

export function isAnySideMenuOpen(stores = menuStores()): boolean {
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
    for (let i = 0; i < 20 && isAnySideMenuOpen(stores); i++) await new Promise(r => setTimeout(r, 50));
    await new Promise(r => setTimeout(r, SIDE_MENU_CLOSE_ANIMATION_MS));
}

// showModal of @decky/ui, but on Windows the dialog opens in the window the side panel belongs to.
// Decky's showModal opens dialogs in Steam's main window (the GamepadUI_Full_Root tree). On SteamOS that's the only
// UI window, so it's always right. On Windows the side panel over a game belongs to the Steam overlay, a window of
// its own over the game (tree GamepadUI_Overlay_<appid>_Root); a dialog opened from there landed in Big Picture,
// which took the focus away from the game and kept it after the dialog closed. Here the dialog goes to the root
// window of the active navigation context: the overlay over a game, Big Picture otherwise.
type ShowModalArgs = Parameters<typeof deckyShowModal>;

function activeRootWindow(): Window | undefined {
    try {
        const root = (getGamepadNavigationTrees() || []).find((t: any) =>
            t?.m_ID === 'GamepadUI_Full_Root' || /^GamepadUI_Overlay_.*_Root$/.test(t?.m_ID || ''));
        return root?.Root?.Element?.ownerDocument?.defaultView || undefined;
    } catch {
        return undefined;
    }
}

export const showModal = (modal: ShowModalArgs[0], parent?: ShowModalArgs[1], props?: ShowModalArgs[2]) =>
    deckyShowModal(modal, parent ?? activeRootWindow(), props);
