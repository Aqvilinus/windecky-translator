// src/deckyState.ts edge cases (timers, a missing Decky). The reload itself is tested end to end in
// tests/integration/plugin.test.ts.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { adoptActivePlugin, type DeckyPluginEntry } from '../../src/deckyState';

const NAME = 'WinDecky Translator';

function installDecky(plugins: DeckyPluginEntry[], active: DeckyPluginEntry | null) {
    const state = {
        _plugins: plugins,
        _activePlugin: active,
        setActivePlugin: vi.fn((name: string) => { state._activePlugin = state._plugins.find(p => p.name === name) ?? null; }),
    };
    (globalThis as unknown as { window: unknown }).window = { DeckyPluginLoader: { deckyState: state } };
    return state;
}

describe('adoptActivePlugin', () => {
    beforeEach(() => { vi.useFakeTimers(); });
    afterEach(() => { vi.useRealTimers(); delete (globalThis as { window?: unknown }).window; });

    it('does nothing when the side menu already shows this instance or nothing', () => {
        const current = { name: NAME, content: 'new' };
        const state = installDecky([current], current);
        adoptActivePlugin(NAME, p => p.content === 'new');
        vi.advanceTimersByTime(500);
        state._activePlugin = null;
        vi.advanceTimersByTime(500);
        expect(state.setActivePlugin).not.toHaveBeenCalled();
    });

    it('gives up when the plugin never shows up, and survives a missing Decky', () => {
        const state = installDecky([], null);
        const stop = adoptActivePlugin(NAME, () => true);
        vi.advanceTimersByTime(20000);
        expect(vi.getTimerCount()).toBe(0);
        stop();
        delete (globalThis as { window?: unknown }).window;
        adoptActivePlugin(NAME, () => true);
        vi.advanceTimersByTime(20000);
        expect(state.setActivePlugin).not.toHaveBeenCalled();
    });
});
