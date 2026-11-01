// The OCR and translation engines, by the ids the backend uses (main.py SETTING_DEFAULTS ocr_provider /
// translation_provider, py_modules/providers/__init__.py ProviderManager).

export type OcrEngine = 'chromescreenai' | 'windows_ocr' | 'ocrspace' | 'googlecloud' | 'gemini_vision';
export type TranslationEngine = 'freegoogle' | 'googlecloud' | 'ct2' | 'llm';

// Short names for status lines: the main tab, the overlay's progress pill, the translation cache list
export const OCR_ENGINE_LABELS: Record<OcrEngine, string> = {
    chromescreenai: 'On-Device',
    windows_ocr: 'On-Device (Windows)',
    ocrspace: 'OCR.space',
    googlecloud: 'Google Cloud',
    gemini_vision: 'Gemini Vision',
};

export const TRANSLATION_ENGINE_LABELS: Record<TranslationEngine, string> = {
    freegoogle: 'Google Translate',
    googlecloud: 'Google Cloud',
    ct2: 'On-Device',
    llm: 'AI',
};

// Engines that work over the internet: the main tab checks they can be reached
export const WEB_OCR_ENGINES = new Set<string>(['gemini_vision', 'googlecloud', 'ocrspace']);
export const WEB_TRANSLATION_ENGINES = new Set<string>(['freegoogle', 'googlecloud', 'llm']);
