// src/SettingsContext.tsx settingsFromBackend: the backend's settings as the frontend's.
import { describe, expect, it, vi } from 'vitest';

let reply: unknown = {};
vi.mock('@decky/api', () => ({ callable: () => vi.fn(() => Promise.resolve(reply)), toaster: { toast: vi.fn() } }));
vi.mock('@decky/ui', () => ({ Router: {} }));
// Steam provides React at runtime; the module only needs these names to load
vi.mock('react', () => ({ default: {}, createContext: () => ({}), useContext: vi.fn(), useEffect: vi.fn(), useReducer: vi.fn() }));

const { settingsFromBackend, loadSettings } = await import('../../src/SettingsContext');

describe('settingsFromBackend', () => {
    it('keeps a stored 0 (the slider allows it)', () => {
        expect(settingsFromBackend({ confidence_threshold: 0 }).confidenceThreshold).toBe(0);
    });

    it('gives a missing setting its default', () => {
        const s = settingsFromBackend({ target_language: 'ru' });
        expect(s.targetLanguage).toBe('ru');
        expect(s.confidenceThreshold).toBe(0.6);
        expect(s.enabled).toBe(true);
        expect(s.ocrProvider).toBe('chromescreenai');
    });
});

describe('loadSettings', () => {
    it('gives the translator what Ctrl+Alt+T needs', async () => {
        reply = { input_language: 'de', target_language: 'ru', ocr_provider: 'windows_ocr', gemini_api_key: 'AIz…k3Fz' };
        const applied: unknown[] = [];
        await loadSettings({ applySettings: (s: unknown) => applied.push(s) } as never);
        expect(applied).toEqual([expect.objectContaining({
            inputLanguage: 'de', targetLanguage: 'ru', ocrProvider: 'windows_ocr', geminiApiKey: 'AIz…k3Fz',
            googleApiKey: '', enabled: true,
        })]);
    });
});
