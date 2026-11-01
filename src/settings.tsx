// The plugin's settings: read from the backend, which stores them and gives each its default (main.py
// get_all_settings, plugin_settings.SETTING_DEFAULTS); each change is saved there and given to the translator.
import React, { createContext, useContext, useEffect, useState } from 'react';
import { PanelSection, PanelSectionRow } from '@decky/ui';
import { toaster } from '@decky/api';
import { backend, BackendSettings } from './backend';
import { Translator } from './translator';
import { logger } from './log';
import type { OcrProvider, TranslationProvider } from './providers';

// API keys: the backend hands out only their first 3 and last 4 characters (main.py mask_key), and saving that
// same text back changes nothing. A key typed in a dialog is kept here in the same shortened form.
const API_KEY_SETTINGS = new Set<string>(['googleApiKey', 'geminiApiKey', 'groqApiKey', 'llmCustomApiKey']);

export function maskKey(value: string): string {
    if (!value || value.includes('…')) return value;
    if (value.length < 12) return value.length > 4 ? '…' + value.slice(-2) : '…';
    return `${value.slice(0, 3)}…${value.slice(-4)}`;
}

export interface Settings {
    sourceLanguage: string;
    targetLanguage: string;
    enabled: boolean;
    confidenceThreshold: number;
    chromeScreenAiKeepAlive: boolean; // its worker stays alive between requests
    nllbKeepAlive: boolean; // the NLLB worker stays alive between requests
    pauseGameOnOverlay: boolean;
    ocrProvider: OcrProvider;
    translationProvider: TranslationProvider;
    googleApiKey: string; // Google Cloud: OCR and translation
    geminiApiKey: string;
    geminiModel: string; // Gemini Vision's
    debugMode: boolean;
    fontScale: number; // the overlay's text, for external monitors
    translationCacheEnabled: boolean;
    // AI translation (providers/llm_translate.py)
    llmService: 'gemini' | 'groq' | 'custom';
    llmGeminiModel: string;
    llmGroqModel: string;
    llmCustomModel: string;
    llmCustomUrl: string;
    groqApiKey: string;
    llmCustomApiKey: string;
}

// A setting's name in the backend: targetLanguage -> target_language
const backendKey = (key: string): string => key.replace(/[A-Z]/g, c => '_' + c.toLowerCase());

// The backend's settings with the frontend's names: target_language -> targetLanguage
export function settingsFromBackend(stored: BackendSettings): Settings {
    return Object.fromEntries(Object.entries(stored).map(
        ([key, value]) => [key.replace(/_([a-z0-9])/g, (_, c) => c.toUpperCase()), value])) as Settings;
}

// The backend's settings into the translator; null if they can't be read. Called at plugin start (index.tsx): Decky
// renders the panel, and with it SettingsProvider, only while the panel is open, but Ctrl+Alt+T works from the start.
export async function loadSettings(translator: Translator): Promise<Settings | null> {
    try {
        const settings = settingsFromBackend(await backend.getAllSettings());
        translator.applySettings(settings);
        logger.debug('settings', 'Settings', settings);
        return settings;
    } catch (error) {
        logger.error('settings', 'Error loading settings', error);
        return null;
    }
}

interface SettingsContextType {
    settings: Settings;
    updateSetting: (key: keyof Settings, value: any, label?: string) => Promise<boolean>;
}

const SettingsContext = createContext<SettingsContextType | undefined>(undefined);

// Its children render once the settings are read
export const SettingsProvider: React.FC<{ children: React.ReactNode; translator: Translator }> = (
    { children, translator }) => {
    const [settings, setSettings] = useState<Settings | null | 'failed'>(null);

    useEffect(() => {
        loadSettings(translator).then(loaded => setSettings(loaded ?? 'failed'));
    }, []);

    // every change reaches the translator, which keeps what Ctrl+Alt+T needs
    useEffect(() => {
        if (settings && settings !== 'failed') translator.applySettings(settings);
    }, [settings]);

    const updateSetting = async (key: keyof Settings, value: any, label?: string): Promise<boolean> => {
        const shown = API_KEY_SETTINGS.has(key) && typeof value === 'string' ? maskKey(value) : value;
        setSettings(prev => prev && prev !== 'failed' ? { ...prev, [key]: shown } : prev);
        try {
            if (await backend.setSetting(backendKey(key), value)) return true;
        } catch (error) {
            logger.error('settings', `Failed to update ${key}`, error);
        }
        const title = `Failed to update ${label || key}`;
        toaster.toast({ title, body: title, duration: 2000, critical: true });
        return false;
    };

    if (!settings || settings === 'failed') {
        return (
            <PanelSection>
                <PanelSectionRow>
                    <div>{settings ? "Couldn't read the settings (details in the plugin log)" : "Loading..."}</div>
                </PanelSectionRow>
            </PanelSection>
        );
    }
    return (
        <SettingsContext.Provider value={{ settings, updateSetting }}>
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
