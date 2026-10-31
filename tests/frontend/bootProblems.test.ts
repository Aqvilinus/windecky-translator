// src/windows.ts showBootProblems / listenForProblems: what the backend couldn't load or later finds broken is shown
// as toasts.
import { beforeEach, describe, expect, it, vi } from 'vitest';

const toasts: Array<{ title: string; body: string }> = [];
let reply: () => Promise<unknown> = () => Promise.resolve([]);
const listeners: Record<string, (...args: unknown[]) => void> = {};

vi.mock('@decky/api', () => ({
    callable: () => vi.fn(() => reply()),
    toaster: { toast: vi.fn((t: { title: string; body: string }) => { toasts.push(t); }) },
    addEventListener: vi.fn((event: string, listener: (...args: unknown[]) => void) => { listeners[event] = listener; }),
    removeEventListener: vi.fn((event: string) => { delete listeners[event]; }),
}));
vi.mock('@decky/ui', () => ({ Router: {} }));

const { showBootProblems, listenForProblems } = await import('../../src/windows');

describe('showBootProblems', () => {
    beforeEach(() => { toasts.length = 0; });

    it('shows one toast per problem', async () => {
        reply = () => Promise.resolve(['Screen capture is unavailable: x', 'The translation overlay is unavailable: y']);
        await showBootProblems('WinDecky Translator');
        expect(toasts.map(t => t.body)).toEqual(['Screen capture is unavailable: x', 'The translation overlay is unavailable: y']);
        expect(toasts[0].title).toBe('WinDecky Translator');
    });

    it('shows nothing when all is well', async () => {
        reply = () => Promise.resolve([]);
        await showBootProblems('t');
        expect(toasts).toEqual([]);
    });

    it('stays quiet when the backend call fails', async () => {
        reply = () => Promise.reject(new Error('no backend'));
        await showBootProblems('t');
        expect(toasts).toEqual([]);
    });
});

describe('listenForProblems', () => {
    beforeEach(() => { toasts.length = 0; });

    it('shows a toast for each problem the backend reports, until stopped', () => {
        const stop = listenForProblems('WinDecky Translator');
        listeners['translator_problem']("The translation overlay doesn't work: draw failed");
        expect(toasts.map(t => t.body)).toEqual(["The translation overlay doesn't work: draw failed"]);
        stop();
        expect(listeners['translator_problem']).toBeUndefined();
    });
});
