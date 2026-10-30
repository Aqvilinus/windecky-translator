// showModal of @decky/ui, but on Windows the dialog opens in the window the side panel belongs to.
// Decky's showModal opens dialogs in Steam's main window (the GamepadUI_Full_Root tree). On SteamOS that's the only
// UI window, so it's always right. On Windows the side panel over a game belongs to the Steam overlay, a window of
// its own over the game (tree GamepadUI_Overlay_<appid>_Root); a dialog opened from there landed in Big Picture,
// which took the focus away from the game and kept it after the dialog closed. Here the dialog goes to the root
// window of the active navigation context: the overlay over a game, Big Picture otherwise.
import { getGamepadNavigationTrees, showModal as deckyShowModal } from '@decky/ui';

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
