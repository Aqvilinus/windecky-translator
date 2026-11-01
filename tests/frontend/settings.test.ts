// src/settings.tsx: the backend's settings with the frontend's names, given to the translator.
import { describe, expect, it, vi } from 'vitest';

let reply: unknown = {};
vi.mock('@decky/api', () => ({ callable: () => vi.fn(() => Promise.resolve(reply)), toaster: { toast: vi.fn() } }));
vi.mock('@decky/ui', () => ({ PanelSection: {}, PanelSectionRow: {} }));
// Steam provides React at runtime; the module only needs these names to load
vi.mock('react', () => ({ default: {}, createContext: () => ({}), useContext: vi.fn(), useEffect: vi.fn(), useState: vi.fn() }));

const { settingsFromBackend, loadSettings } = await import('../../src/settings');

describe('settingsFromBackend', () => {
    it('names each setting as the frontend does, values as stored', () => {
        expect(settingsFromBackend({ target_language: 'ru', confidence_threshold: 0, ct2_persistent_mode: true,
                                     llm_custom_api_key: 'sk-…k3Fz' })).toEqual({
            targetLanguage: 'ru', confidenceThreshold: 0, ct2PersistentMode: true, llmCustomApiKey: 'sk-…k3Fz' });
    });
});

describe('loadSettings', () => {
    it('gives the translator what Ctrl+Alt+T needs', async () => {
        reply = { input_language: 'de', target_language: 'ru', ocr_provider: 'windows_ocr', gemini_api_key: 'AIz…k3Fz',
                  google_api_key: '', enabled: true };
        const applied: unknown[] = [];
        await loadSettings({ applySettings: (s: unknown) => applied.push(s) } as never);
        expect(applied).toEqual([expect.objectContaining({
            inputLanguage: 'de', targetLanguage: 'ru', ocrProvider: 'windows_ocr', geminiApiKey: 'AIz…k3Fz',
            googleApiKey: '', enabled: true,
        })]);
    });
});
