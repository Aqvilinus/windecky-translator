// The OCR and translation engines, by the ids the backend uses (main.py SETTING_DEFAULTS ocr_provider /
// translation_provider, py_modules/providers/__init__.py ProviderRegistry), and the AI translation's services.
import type { Settings } from './settings';

export type OcrProvider = 'chrome_screen_ai' | 'windows_ocr' | 'google_cloud' | 'gemini_vision';
export type TranslationProvider = 'google_web' | 'google_cloud' | 'nllb' | 'llm';

// Short names for status lines: the main tab, the overlay's progress pill, the translation cache list
export const OCR_PROVIDER_LABELS: Record<OcrProvider, string> = {
    chrome_screen_ai: 'On-Device',
    windows_ocr: 'On-Device (Windows)',
    google_cloud: 'Google Cloud',
    gemini_vision: 'Gemini Vision',
};

export const TRANSLATION_PROVIDER_LABELS: Record<TranslationProvider, string> = {
    google_web: 'Google Translate',
    google_cloud: 'Google Cloud',
    nllb: 'On-Device',
    llm: 'AI',
};

// Engines that report how sure they are of each line: the OCR confidence slider is shown for these only
export const CONFIDENCE_OCR_PROVIDERS = new Set<string>(['chrome_screen_ai', 'google_cloud']);

// Engines that work over the internet: the main tab checks they can be reached
export const WEB_OCR_PROVIDERS = new Set<string>(['gemini_vision', 'google_cloud']);
export const WEB_TRANSLATION_PROVIDERS = new Set<string>(['google_web', 'google_cloud', 'llm']);

// AI translation (translation provider "llm", py_modules/providers/llm_translate.py): which service, its key and model
export const LLM_SERVICE_LABELS: Record<string, string> = {
    gemini: 'Gemini',
    groq: 'Groq',
    custom: 'Custom',
};

// Shown before the service has listed the models the key can use
export const LLM_DEFAULT_MODELS: Record<string, string[]> = {
    gemini: ['gemini-flash-lite-latest', 'gemini-flash-latest'],
    groq: ['openai/gpt-oss-120b', 'openai/gpt-oss-20b'],
    custom: [],
};

export const LLM_MODEL_SETTING: Record<string, keyof Settings> = {
    gemini: 'llmGeminiModel',
    groq: 'llmGroqModel',
    custom: 'llmCustomModel',
};

export const LLM_KEY_SETTING: Record<string, keyof Settings> = {
    gemini: 'geminiApiKey',  // shared with Gemini Vision
    groq: 'groqApiKey',
    custom: 'llmCustomApiKey',
};

export function llmModel(s: Settings): string {
    return String(s[LLM_MODEL_SETTING[s.llmService]] || '');
}

export function llmConfigured(s: Settings): boolean {
    if (s.llmService === 'custom') return !!(s.llmCustomUrl && s.llmCustomModel);
    return !!s[LLM_KEY_SETTING[s.llmService]];
}
