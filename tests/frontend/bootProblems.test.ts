// src/windows.ts showBootProblems: what the backend couldn't load is shown as toasts.
import { beforeEach, describe, expect, it, vi } from 'vitest';

const toasts: Array<{ title: string; body: string }> = [];
let reply: () => Promise<unknown> = () => Promise.resolve([]);

vi.mock('@decky/api', () => ({
    call: vi.fn(() => reply()),
    toaster: { toast: vi.fn((t: { title: string; body: string }) => { toasts.push(t); }) },
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
}));
vi.mock('@decky/ui', () => ({ Router: {} }));

const { showBootProblems } = await import('../../src/windows');

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
