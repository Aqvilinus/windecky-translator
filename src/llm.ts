// AI translation (translation provider "llm", py_modules/providers/llm_translate.py): which service, its key and model.
import type { Settings } from './SettingsContext';

export const LLM_BACKEND_LABELS: Record<string, string> = {
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
    return String(s[LLM_MODEL_SETTING[s.llmBackend]] || '');
}

export function llmConfigured(s: Settings): boolean {
    if (s.llmBackend === 'custom') return !!(s.llmCustomUrl && s.llmCustomModel);
    return !!s[LLM_KEY_SETTING[s.llmBackend]];
}
