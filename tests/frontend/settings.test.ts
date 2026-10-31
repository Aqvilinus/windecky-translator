// src/SettingsContext.tsx settingsFromBackend: the backend's settings as the frontend's.
import { describe, expect, it, vi } from 'vitest';

let reply: unknown = {};
vi.mock('@decky/api', () => ({ call: vi.fn(() => Promise.resolve(reply)), toaster: { toast: vi.fn() } }));
vi.mock('@decky/ui', () => ({ Router: {} }));
// Steam provides React at runtime; the module only needs these names to load
vi.mock('react', () => ({ default: {}, createContext: () => ({}), useContext: vi.fn(), useEffect: vi.fn(), useReducer: vi.fn() }));

const { settingsFromBackend, loadSettingsIntoLogic } = await import('../../src/SettingsContext');

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

describe('loadSettingsIntoLogic', () => {
    it('gives the translator logic what Ctrl+Alt+T needs', async () => {
        reply = { input_language: 'de', target_language: 'ru', ocr_provider: 'windows_ocr', gemini_api_key: 'AIz…k3Fz' };
        const calls: string[] = [];
        const logic = new Proxy({}, { get: (_t, name) => (value: unknown) => calls.push(`${String(name)}=${value}`) });
        await loadSettingsIntoLogic(logic as never);
        expect(calls).toEqual(expect.arrayContaining([
            'setInputLanguage=de', 'setTargetLanguage=ru', 'setOcrProvider=windows_ocr', 'setHasGeminiApiKey=true',
            'setHasGoogleApiKey=false', 'setEnabled=true',
        ]));
    });
});
