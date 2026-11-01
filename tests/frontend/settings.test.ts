// src/SettingsContext.tsx settingsFromBackend: the backend's settings as the frontend's.
import { describe, expect, it, vi } from 'vitest';

vi.mock('@decky/api', () => ({ call: vi.fn(), toaster: { toast: vi.fn() } }));
vi.mock('@decky/ui', () => ({ Router: {} }));
// Steam provides React at runtime; the module only needs these names to load
vi.mock('react', () => ({ default: {}, createContext: () => ({}), useContext: vi.fn(), useEffect: vi.fn(), useReducer: vi.fn() }));

const { settingsFromBackend } = await import('../../src/SettingsContext');

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
