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
            const serverSettings = await call<[], any>('get_all_settings');

            if (serverSettings) {

                // Map backend settings to frontend settings
                const mappedSettings: Partial<Settings> = {
                    inputLanguage: serverSettings.input_language,
                    targetLanguage: serverSettings.target_language,
                    enabled: serverSettings.enabled,
                    confidenceThreshold: serverSettings.confidence_threshold || 0.6, // Add default if not present
                    chromeScreenAiPersistentMode: serverSettings.chromescreenai_persistent_mode ?? false,
                    ct2PersistentMode: serverSettings.ct2_persistent_mode ?? false,
                    pauseGameOnOverlay: serverSettings.pause_game_on_overlay || false, // Add default if not present
                    ocrProvider: serverSettings.ocr_provider || "chromescreenai", // OCR provider setting
                    translationProvider: serverSettings.translation_provider || "freegoogle", // Translation provider setting
                    googleApiKey: serverSettings.google_api_key || "", // Google API key
                    geminiApiKey: serverSettings.gemini_api_key || "", // Gemini API key
                    geminiModel: serverSettings.gemini_model || "gemini-3.5-flash",
                    debugMode: serverSettings.debug_mode || false,
                    fontScale: serverSettings.font_scale ?? 1.0,
                    customRecognitionSettings: serverSettings.custom_recognition_settings ?? false,
                    translationCacheEnabled: serverSettings.translation_cache_enabled ?? true,
                    llmBackend: serverSettings.llm_backend ?? "gemini",
                    llmGeminiModel: serverSettings.llm_gemini_model ?? LLM_DEFAULT_MODELS.gemini[0],
                    llmGroqModel: serverSettings.llm_groq_model ?? LLM_DEFAULT_MODELS.groq[0],
                    llmCustomModel: serverSettings.llm_custom_model ?? "",
                    llmCustomUrl: serverSettings.llm_custom_url ?? "",
                    groqApiKey: serverSettings.groq_api_key ?? "",
                    llmCustomApiKey: serverSettings.llm_custom_api_key ?? "",
                };

                // Update settings in context
                dispatch({ type: 'INITIALIZE_SETTINGS', settings: mappedSettings });

                // Update logic instance with settings
                logic.setInputLanguage(serverSettings.input_language);
                logic.setTargetLanguage(serverSettings.target_language);
                logic.setEnabled(serverSettings.enabled);
                logic.setConfidenceThreshold(serverSettings.confidence_threshold || 0.6); // Set in logic
                logger.setEnabled(serverSettings.debug_mode || false); // Set debug mode for logger

                // Set provider settings for upfront API key validation
                logic.setOcrProvider(serverSettings.ocr_provider || "chromescreenai");
                logic.setTranslationProvider(serverSettings.translation_provider || "freegoogle");
                logic.setHasGoogleApiKey(!!serverSettings.google_api_key);
                logic.setHasGeminiApiKey(!!serverSettings.gemini_api_key);

                logic.setFontScale(serverSettings.font_scale ?? 1.0);

                logger.info('SettingsContext', 'All settings loaded successfully');
                logger.logObject('SettingsContext', 'Settings', mappedSettings);
            } else {
                logger.error('SettingsContext', 'Failed to load settings');
            }
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