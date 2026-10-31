// src/SettingsContext.tsx
import React, { createContext, useContext, useEffect, useReducer } from 'react';
import { backend, BackendSettings } from './backend';
import { GameTranslatorLogic } from './Translator';
import { logger } from './Logger';
import { LLM_DEFAULT_MODELS } from './llm';
import type { OcrEngine, TranslationEngine } from './providers';

// API keys: the backend hands out only their first 3 and last 4 characters (main.py display_key), and saving that
// same text back changes nothing. A key typed in a dialog is kept here in the same shortened form.
const SECRET_SETTINGS = new Set<string>(['googleApiKey', 'geminiApiKey', 'groqApiKey', 'llmCustomApiKey']);

export function displayKey(value: string): string {
    if (!value || value.includes('…')) return value;
    if (value.length < 12) return value.length > 4 ? '…' + value.slice(-2) : '…';
    return `${value.slice(0, 3)}…${value.slice(-4)}`;
}

// Define the settings interface
export interface Settings {
    inputLanguage: string;
    targetLanguage: string;
    enabled: boolean;
    initialized: boolean;
    confidenceThreshold: number; // New setting for confidence threshold
    chromeScreenAiPersistentMode: boolean; // Keep Chrome Screen AI worker alive between requests
    ct2PersistentMode: boolean; // Keep CT2/NLLB worker alive between requests
    pauseGameOnOverlay: boolean; // Setting to control pausing game when overlay is shown
    ocrProvider: OcrEngine;
    translationProvider: TranslationEngine;
    googleApiKey: string; // Google Cloud Vision API key for text recognition
    geminiApiKey: string; // Gemini API key for Gemini Vision (free tier available)
    geminiModel: string; // Gemini model to use
    debugMode: boolean; // Debug mode for verbose console logging
    fontScale: number; // Overlay font scale multiplier for external monitors
    customRecognitionSettings: boolean;
    translationCacheEnabled: boolean;
    llmBackend: 'gemini' | 'groq' | 'custom'; // AI translation (providers/llm_translate.py)
    llmGeminiModel: string; // AI translation (providers/llm_translate.py)
    llmGroqModel: string; // AI translation (providers/llm_translate.py)
    llmCustomModel: string; // AI translation (providers/llm_translate.py)
    llmCustomUrl: string; // AI translation (providers/llm_translate.py)
    groqApiKey: string; // AI translation (providers/llm_translate.py)
    llmCustomApiKey: string; // AI translation (providers/llm_translate.py)
}

// Define action types
type SettingsAction =
    | { type: 'INITIALIZE_SETTINGS', settings: Partial<Settings> }
    | { type: 'UPDATE_SETTING', key: keyof Settings, value: any }
    | { type: 'SET_INITIALIZED', initialized: boolean };

// Define the initial state
const initialSettings: Settings = {
    inputLanguage: "",
    targetLanguage: "",
    enabled: true,
    initialized: false,
    confidenceThreshold: 0.6, // Default confidence threshold
    chromeScreenAiPersistentMode: false,
    ct2PersistentMode: false,
    pauseGameOnOverlay: false, // Default to not pausing game
    ocrProvider: "chromescreenai", // Default to chromescreenai (Chrome Screen AI) provider
    translationProvider: "freegoogle", // Default to free Google Translate
    googleApiKey: "", // Empty by default, only needed for Google Cloud
    geminiApiKey: "", // Empty by default, needed for Gemini Vision
    geminiModel: "gemini-3.5-flash", // Default Gemini model
    debugMode: false, // Debug mode off by default
    fontScale: 1.0,
    customRecognitionSettings: false,
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
    customRecognitionSettings: 'custom_recognition_settings',
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

// What a setting changes in the translator logic, which keeps what Ctrl+Alt+T needs
function applyToLogic(logic: GameTranslatorLogic, key: keyof SavedSettings, value: any): void {
    switch (key) {
        case 'inputLanguage': logic.setInputLanguage(value); break;
        case 'targetLanguage': logic.setTargetLanguage(value); break;
        case 'enabled': logic.setEnabled(value); break;
        case 'confidenceThreshold': logic.setConfidenceThreshold(value); break;
        case 'debugMode': logger.setEnabled(value); break;
        case 'fontScale': logic.setFontScale(value); break;
        case 'ocrProvider': logic.setOcrProvider(value); break;
        case 'translationProvider': logic.setTranslationProvider(value); break;
        case 'googleApiKey': logic.setHasGoogleApiKey(!!value); break;
        case 'geminiApiKey': logic.setHasGeminiApiKey(!!value); break;
    }
}

// The backend's settings into the logic; null if they can't be read. Called at plugin start (index.tsx): Decky
// renders the panel, and with it SettingsProvider, only while the panel is open, but Ctrl+Alt+T works from the start.
export async function loadSettingsIntoLogic(logic: GameTranslatorLogic): Promise<SavedSettings | null> {
    try {
        const settings = settingsFromBackend(await backend.getAllSettings());
        for (const key of SAVED_KEYS) applyToLogic(logic, key, settings[key]);
        logger.logObject('SettingsContext', 'Settings', settings);
        return settings;
    } catch (error) {
        logger.error('SettingsContext', 'Error loading settings', error);
        return null;
    }
}

// Create the reducer
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

// Create the context
interface SettingsContextType {
    settings: Settings;
    updateSetting: (key: keyof Settings, value: any, label?: string) => Promise<boolean>;
    initialized: boolean;
}

const SettingsContext = createContext<SettingsContextType | undefined>(undefined);

// Create the provider component
interface SettingsProviderProps {
    children: React.ReactNode;
    logic: GameTranslatorLogic;
}

export const SettingsProvider: React.FC<SettingsProviderProps> = ({
                                                                      children,
                                                                      logic
                                                                  }) => {
    const [settings, dispatch] = useReducer(settingsReducer, initialSettings);

    const loadAllSettings = async () => {
        const loaded = await loadSettingsIntoLogic(logic);
        if (loaded) dispatch({ type: 'INITIALIZE_SETTINGS', settings: loaded });
        dispatch({ type: 'SET_INITIALIZED', initialized: true });
    };

    // Save one setting: the panel's state, the logic, the backend
    const updateSetting = async (key: keyof Settings, value: any, label?: string): Promise<boolean> => {
        if (key === 'initialized') return true;
        dispatch({
            type: 'UPDATE_SETTING', key,
            value: SECRET_SETTINGS.has(key) && typeof value === 'string' ? displayKey(value) : value,
        });
        applyToLogic(logic, key, value);
        try {
            if (await backend.setSetting(BACKEND_KEYS[key], value)) return true;
        } catch (error) {
            logger.error('SettingsContext', `Failed to update ${key}`, error);
        }
        logic.notify(`Failed to update ${label || key}`, 2000);
        return false;
    };

    // Initialize settings on mount
    useEffect(() => {
        loadAllSettings();
    }, []);

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

// Create a hook for using the settings
export const useSettings = () => {
    const context = useContext(SettingsContext);
    if (!context) {
        throw new Error('useSettings must be used within a SettingsProvider');
    }
    return context;
};