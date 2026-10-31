// src/windows.ts closeAllSideMenus: closes the side menu in every Steam window; Steam internals that changed only
// turn parts of it off, they never stop a translation from starting.
import { describe, expect, it, vi } from 'vitest';

let menuOpen = true;
const store = {
    IsAnySideMenuVisible: () => menuOpen,
    CloseSideMenus: vi.fn(() => { menuOpen = false; }),
};

vi.mock('@decky/api', () => ({ call: vi.fn(), toaster: { toast: vi.fn() }, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
vi.mock('@decky/ui', () => ({
    Router: {
        CloseSideMenus: () => { throw new TypeError('CloseSideMenus is not a function'); },  // renamed by Steam
        WindowStore: { SteamUIWindows: [{ MenuStore: store }] },
    },
}));

const { closeAllSideMenus } = await import('../../src/windows');

describe('closeAllSideMenus', () => {
    it('closes the menus through the window stores even when Router.CloseSideMenus fails', async () => {
        await expect(closeAllSideMenus()).resolves.toBeUndefined();
        expect(store.CloseSideMenus).toHaveBeenCalled();
        expect(menuOpen).toBe(false);
    });
});
