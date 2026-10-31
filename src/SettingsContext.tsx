// src/SettingsContext.tsx
import React, { createContext, useContext, useEffect, useReducer } from 'react';
import { call } from '@decky/api';
import { GameTranslatorLogic } from './Translator';
import { logger } from './Logger';
import { LLM_DEFAULT_MODELS } from './llm';

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
    ocrProvider: 'chromescreenai' | 'windows_ocr' | 'ocrspace' | 'googlecloud' | 'gemini_vision'; // OCR provider
    translationProvider: 'freegoogle' | 'googlecloud' | 'ct2' | 'llm'; // Translation provider
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

// main.py get_all_settings
type BackendSettings = Record<string, any>;

// The backend's settings as the frontend's (a missing one gets its default; a stored 0 or "" stays)
export function settingsFromBackend(server: BackendSettings): Omit<Settings, 'initialized'> {
    const pick = <K extends keyof Settings>(key: K, backendKey: string): Settings[K] =>
        server[backendKey] ?? initialSettings[key];
    return {
        inputLanguage: pick('inputLanguage', 'input_language'),
        targetLanguage: pick('targetLanguage', 'target_language'),
        enabled: pick('enabled', 'enabled'),
        confidenceThreshold: pick('confidenceThreshold', 'confidence_threshold'),
        chromeScreenAiPersistentMode: pick('chromeScreenAiPersistentMode', 'chromescreenai_persistent_mode'),
        ct2PersistentMode: pick('ct2PersistentMode', 'ct2_persistent_mode'),
        pauseGameOnOverlay: pick('pauseGameOnOverlay', 'pause_game_on_overlay'),
        ocrProvider: pick('ocrProvider', 'ocr_provider'),
        translationProvider: pick('translationProvider', 'translation_provider'),
        googleApiKey: pick('googleApiKey', 'google_api_key'),
        geminiApiKey: pick('geminiApiKey', 'gemini_api_key'),
        geminiModel: pick('geminiModel', 'gemini_model'),
        debugMode: pick('debugMode', 'debug_mode'),
        fontScale: pick('fontScale', 'font_scale'),
        customRecognitionSettings: pick('customRecognitionSettings', 'custom_recognition_settings'),
        translationCacheEnabled: pick('translationCacheEnabled', 'translation_cache_enabled'),
        llmBackend: pick('llmBackend', 'llm_backend'),
        llmGeminiModel: pick('llmGeminiModel', 'llm_gemini_model'),
        llmGroqModel: pick('llmGroqModel', 'llm_groq_model'),
        llmCustomModel: pick('llmCustomModel', 'llm_custom_model'),
        llmCustomUrl: pick('llmCustomUrl', 'llm_custom_url'),
        groqApiKey: pick('groqApiKey', 'groq_api_key'),
        llmCustomApiKey: pick('llmCustomApiKey', 'llm_custom_api_key'),
    };
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

    // Load all settings at once
    const loadAllSettings = async () => {
        try {
            const mapped = settingsFromBackend(await call<[], BackendSettings>('get_all_settings'));
            dispatch({ type: 'INITIALIZE_SETTINGS', settings: mapped });

            // Update logic instance with settings
            logic.setInputLanguage(mapped.inputLanguage);
            logic.setTargetLanguage(mapped.targetLanguage);
            logic.setEnabled(mapped.enabled);
            logic.setConfidenceThreshold(mapped.confidenceThreshold);
            logger.setEnabled(mapped.debugMode);

            // Set provider settings for upfront API key validation
            logic.setOcrProvider(mapped.ocrProvider);
            logic.setTranslationProvider(mapped.translationProvider);
            logic.setHasGoogleApiKey(!!mapped.googleApiKey);
            logic.setHasGeminiApiKey(!!mapped.geminiApiKey);

            logic.setFontScale(mapped.fontScale);

            logger.info('SettingsContext', 'All settings loaded successfully');
            logger.logObject('SettingsContext', 'Settings', mapped);
        } catch (error) {
            logger.error('SettingsContext', 'Error loading settings', error);
        } finally {
            dispatch({ type: 'SET_INITIALIZED', initialized: true });
        }
    };

    // Update a single setting
    const updateSetting = async (key: keyof Settings, value: any, label?: string): Promise<boolean> => {
        try {
            // Update local state
            dispatch({
                type: 'UPDATE_SETTING', key,
                value: SECRET_SETTINGS.has(key as string) && typeof value === 'string' ? displayKey(value) : value,
            });

            // Map frontend setting key to backend setting key
            const backendKeyMap: Record<keyof Settings, string> = {
                inputLanguage: 'input_language',
                targetLanguage: 'target_language',
                enabled: 'enabled',
                initialized: 'initialized',
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
                llmCustomApiKey: 'llm_custom_api_key'
            };

            // Skip settings that don't need to be saved to backend
            if (key === 'initialized') return true;

            const backendKey = backendKeyMap[key];

            // Update logic based on setting type
            switch (key) {
                case 'inputLanguage':
                    logic.setInputLanguage(value);
                    break;
                case 'targetLanguage':
                    logic.setTargetLanguage(value);
                    break;
                case 'enabled':
                    logic.setEnabled(value);
                    break;
                case 'confidenceThreshold':
                    logic.setConfidenceThreshold(value);
                    break;
                case 'debugMode':
                    logger.setEnabled(value);
                    break;
                case 'fontScale':
                    logic.setFontScale(value);
                    break;
                case 'ocrProvider':
                    logic.setOcrProvider(value);
                    break;
                case 'translationProvider':
                    logic.setTranslationProvider(value);
                    break;
                case 'googleApiKey':
                    logic.setHasGoogleApiKey(!!value);
                    break;
                case 'geminiApiKey':
                    logic.setHasGeminiApiKey(!!value);
                    break;
            }

            // Save to backend
            const result = await call<[string, any], boolean>('set_setting', backendKey, value);

            if (result) {
                // if (label) logic.notify(`${label} updated successfully`);
                return true;
            } else {
                logic.notify(`Failed to update ${label || key}`, 2000);
                return false;
            }
        } catch (error) {
            logger.error('SettingsContext', `Failed to update ${key}`, error);
            logic.notify(`Failed to update ${label || key}`, 2000);
            return false;
        }
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