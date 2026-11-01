import React, { createContext, useContext, useEffect, useReducer } from 'react';
import { toaster } from '@decky/api';
import { backend, BackendSettings } from './backend';
import { Translator } from './translator';
import { logger } from './log';
import { LLM_DEFAULT_MODELS } from './llm';
import type { OcrEngine, TranslationEngine } from './providers';

// API keys: the backend hands out only their first 3 and last 4 characters (main.py mask_key), and saving that
// same text back changes nothing. A key typed in a dialog is kept here in the same shortened form.
const SECRET_SETTINGS = new Set<string>(['googleApiKey', 'geminiApiKey', 'groqApiKey', 'llmCustomApiKey']);

export function displayKey(value: string): string {
    if (!value || value.includes('…')) return value;
    if (value.length < 12) return value.length > 4 ? '…' + value.slice(-2) : '…';
    return `${value.slice(0, 3)}…${value.slice(-4)}`;
}

export interface Settings {
    inputLanguage: string;
    targetLanguage: string;
    enabled: boolean;
    initialized: boolean;
    confidenceThreshold: number;
    chromeScreenAiPersistentMode: boolean; // its worker stays alive between requests
    ct2PersistentMode: boolean; // the CT2/NLLB worker stays alive between requests
    pauseGameOnOverlay: boolean;
    ocrProvider: OcrEngine;
    translationProvider: TranslationEngine;
    googleApiKey: string; // Google Cloud: OCR and translation
    geminiApiKey: string;
    geminiModel: string; // Gemini Vision's
    debugMode: boolean;
    fontScale: number; // the overlay's text, for external monitors
    translationCacheEnabled: boolean;
    // AI translation (providers/llm_translate.py)
    llmBackend: 'gemini' | 'groq' | 'custom';
    llmGeminiModel: string;
    llmGroqModel: string;
    llmCustomModel: string;
    llmCustomUrl: string;
    groqApiKey: string;
    llmCustomApiKey: string;
}

type SettingsAction =
    | { type: 'INITIALIZE_SETTINGS', settings: Partial<Settings> }
    | { type: 'UPDATE_SETTING', key: keyof Settings, value: any }
    | { type: 'SET_INITIALIZED', initialized: boolean };

const initialSettings: Settings = {
    inputLanguage: "",
    targetLanguage: "",
    enabled: true,
    initialized: false,
    confidenceThreshold: 0.6,
    chromeScreenAiPersistentMode: false,
    ct2PersistentMode: false,
    pauseGameOnOverlay: false,
    ocrProvider: "chromescreenai",
    translationProvider: "freegoogle",
    googleApiKey: "",
    geminiApiKey: "",
    geminiModel: "gemini-3.5-flash",
    debugMode: false,
    fontScale: 1.0,
    translationCacheEnabled: true,
    llmBackend: "gemini",
    llmGeminiModel: LLM_DEFAULT_MODELS.gemini[0],
    llmGroqModel: LLM_DEFAULT_MODELS.groq[0],
    llmCustomModel: "",
    llmCustomUrl: "",
    groqApiKey: "",
    llmCustomApiKey: "",
};

// Settings the backend stores (initialized is the panel's own)
type SavedSettings = Omit<Settings, 'initialized'>;

// Each setting's name in the backend (main.py SETTING_DEFAULTS)
const BACKEND_KEYS: Record<keyof SavedSettings, string> = {
    inputLanguage: 'input_language',
    targetLanguage: 'target_language',
    enabled: 'enabled',
    confidenceThreshold: 'confidence_threshold',
    chromeScreenAiPersistentMode: 'chromescreenai_persistent_mode',
    ct2PersistentMode: 'ct2_persistent_mode',
    pauseGameOnOverlay: 'pause_game_on_overlay',
    ocrProvider: 'ocr_provider',
    translationProvider: 'translation_provider',
    googleApiKey: 'google_api_key',
    geminiApiKey: 'gemini_api_key',
    geminiModel: 'gemini_model',
    debugMode: 'debug_mode',
    fontScale: 'font_scale',
    translationCacheEnabled: 'translation_cache_enabled',
    llmBackend: 'llm_backend',
    llmGeminiModel: 'llm_gemini_model',
    llmGroqModel: 'llm_groq_model',
    llmCustomModel: 'llm_custom_model',
    llmCustomUrl: 'llm_custom_url',
    groqApiKey: 'groq_api_key',
    llmCustomApiKey: 'llm_custom_api_key',
};
const SAVED_KEYS = Object.keys(BACKEND_KEYS) as Array<keyof SavedSettings>;

// The backend's settings as the frontend's (a missing one gets its default; a stored 0 or "" stays)
export function settingsFromBackend(server: BackendSettings): SavedSettings {
    const settings: Record<string, unknown> = {};
    for (const key of SAVED_KEYS) settings[key] = server[BACKEND_KEYS[key]] ?? initialSettings[key];
    return settings as SavedSettings;
}

// The backend's settings into the translator; null if they can't be read. Called at plugin start (index.tsx): Decky
// renders the panel, and with it SettingsProvider, only while the panel is open, but Ctrl+Alt+T works from the start.
export async function loadSettings(translator: Translator): Promise<SavedSettings | null> {
    try {
        const settings = settingsFromBackend(await backend.getAllSettings());
        translator.applySettings(settings);
        logger.debug('SettingsContext', 'Settings', settings);
        return settings;
    } catch (error) {
        logger.error('SettingsContext', 'Error loading settings', error);
        return null;
    }
}

function settingsReducer(state: Settings, action: SettingsAction): Settings {
    switch (action.type) {
        case 'INITIALIZE_SETTINGS':
            return { ...state, ...action.settings };
        case 'UPDATE_SETTING':
            return { ...state, [action.key]: action.value };
        case 'SET_INITIALIZED':
            return { ...state, initialized: action.initialized };
        default:
            return state;
    }
}

interface SettingsContextType {
    settings: Settings;
    updateSetting: (key: keyof Settings, value: any, label?: string) => Promise<boolean>;
    initialized: boolean;
}

const SettingsContext = createContext<SettingsContextType | undefined>(undefined);

interface SettingsProviderProps {
    children: React.ReactNode;
    translator: Translator;
}

export const SettingsProvider: React.FC<SettingsProviderProps> = ({
                                                                      children,
                                                                      translator
                                                                  }) => {
    const [settings, dispatch] = useReducer(settingsReducer, initialSettings);

    const loadAllSettings = async () => {
        const loaded = await loadSettings(translator);
        if (loaded) dispatch({ type: 'INITIALIZE_SETTINGS', settings: loaded });
        dispatch({ type: 'SET_INITIALIZED', initialized: true });
    };

    const updateSetting = async (key: keyof Settings, value: any, label?: string): Promise<boolean> => {
        if (key === 'initialized') return true;
        dispatch({
            type: 'UPDATE_SETTING', key,
            value: SECRET_SETTINGS.has(key) && typeof value === 'string' ? displayKey(value) : value,
        });
        try {
            if (await backend.setSetting(BACKEND_KEYS[key], value)) return true;
        } catch (error) {
            logger.error('SettingsContext', `Failed to update ${key}`, error);
        }
        const title = `Failed to update ${label || key}`;
        toaster.toast({ title, body: title, duration: 2000, critical: true });
        return false;
    };

    useEffect(() => {
        loadAllSettings();
    }, []);

    // every change reaches the translator, which keeps what Ctrl+Alt+T needs
    useEffect(() => {
        if (settings.initialized) translator.applySettings(settings);
    }, [settings]);

    return (
        <SettingsContext.Provider value={{
            settings,
            updateSetting,
            initialized: settings.initialized
        }}>
            {children}
        </SettingsContext.Provider>
    );
};

export const useSettings = () => {
    const context = useContext(SettingsContext);
    if (!context) {
        throw new Error('useSettings must be used within a SettingsProvider');
    }
    return context;
};