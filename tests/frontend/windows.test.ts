// src/windows.ts: the translation is forwarded to the backend's overlay window, and a Steam side menu opening over
// it closes it.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const calls: Array<[string, unknown]> = [];
const menus = { open: false };

vi.mock('@decky/api', () => ({
    call: vi.fn((method: string, arg: unknown) => { calls.push([method, arg]); return Promise.resolve(true); }),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
}));
vi.mock('@decky/ui', () => ({
    Router: {
        WindowStore: {
            SteamUIWindows: [
                { MenuStore: { IsAnySideMenuVisible: () => false } },  // Big Picture
                { MenuStore: { IsAnySideMenuVisible: () => menus.open, CloseSideMenus: () => { menus.open = false; } } },
            ],
        },
    },
}));

const { forwardOverlayToBackend } = await import('../../src/windows');

type Listener = (...args: unknown[]) => void;

function fakeImageState() {
    let listeners: Listener[] = [];
    return {
        onStateChanged: (cb: Listener) => { listeners.push(cb); },
        offStateChanged: (cb: Listener) => { listeners = listeners.filter(l => l !== cb); },
        set(visible: boolean) { for (const l of listeners) l(visible, '', [], false, '', '', false, true, 1); },
        get count() { return listeners.length; },
    };
}

const updates = () => calls.filter(c => c[0] === 'native_overlay_update').map(c => (c[1] as { visible: boolean }).visible);

describe('forwardOverlayToBackend', () => {
    beforeEach(() => { vi.useFakeTimers(); calls.length = 0; menus.open = false; });
    afterEach(() => { vi.useRealTimers(); });

    it('forwards every state change to the backend overlay', () => {
        const state = fakeImageState();
        const stop = forwardOverlayToBackend(state as never, vi.fn());
        state.set(true);
        state.set(false);
        expect(updates()).toEqual([true, false]);
        stop();
        expect(state.count).toBe(0);
    });

    it('closes the translation when a side menu opens over it', () => {
        const state = fakeImageState();
        const dismiss = vi.fn(() => state.set(false));
        forwardOverlayToBackend(state as never, dismiss);
        state.set(true);
        vi.advanceTimersByTime(1000);
        expect(dismiss).not.toHaveBeenCalled();
        menus.open = true;
        vi.advanceTimersByTime(300);
        expect(dismiss).toHaveBeenCalledTimes(1);
        expect(updates()).toEqual([true, false]);
    });

    it('keeps a translation that appears while a menu is still closing (Translate from the side menu)', () => {
        const state = fakeImageState();
        const dismiss = vi.fn();
        forwardOverlayToBackend(state as never, dismiss);
        menus.open = true;
        state.set(true);
        vi.advanceTimersByTime(1000);
        expect(dismiss).not.toHaveBeenCalled();
        menus.open = false;
        vi.advanceTimersByTime(300);
        menus.open = true;  // opened again later: that one closes it
        vi.advanceTimersByTime(300);
        expect(dismiss).toHaveBeenCalledTimes(1);
    });

    it('does not watch the menus while no translation is shown', () => {
        const state = fakeImageState();
        const dismiss = vi.fn();
        forwardOverlayToBackend(state as never, dismiss);
        state.set(true);
        state.set(false);
        menus.open = true;
        vi.advanceTimersByTime(1000);
        expect(dismiss).not.toHaveBeenCalled();
    });

    it('stops watching on cleanup', () => {
        const state = fakeImageState();
        const dismiss = vi.fn();
        const stop = forwardOverlayToBackend(state as never, dismiss);
        state.set(true);
        stop();
        menus.open = true;
        vi.advanceTimersByTime(1000);
        expect(dismiss).not.toHaveBeenCalled();
    });
});
