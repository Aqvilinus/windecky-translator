// The OCR and translation engines, by the ids the backend uses (main.py SETTING_DEFAULTS ocr_provider /
// translation_provider, py_modules/providers/__init__.py ProviderRegistry).

export type OcrEngine = 'chromescreenai' | 'windows_ocr' | 'googlecloud' | 'gemini_vision';
export type TranslationEngine = 'freegoogle' | 'googlecloud' | 'ct2' | 'llm';

// Short names for status lines: the main tab, the overlay's progress pill, the translation cache list
export const OCR_ENGINE_LABELS: Record<OcrEngine, string> = {
    chromescreenai: 'On-Device',
    windows_ocr: 'On-Device (Windows)',
    googlecloud: 'Google Cloud',
    gemini_vision: 'Gemini Vision',
};

export const TRANSLATION_ENGINE_LABELS: Record<TranslationEngine, string> = {
    freegoogle: 'Google Translate',
    googlecloud: 'Google Cloud',
    ct2: 'On-Device',
    llm: 'AI',
};

// Engines that report how sure they are of each line: the OCR confidence slider is shown for these only
export const CONFIDENCE_OCR_ENGINES = new Set<string>(['chromescreenai', 'googlecloud']);

// Engines that work over the internet: the main tab checks they can be reached
export const WEB_OCR_ENGINES = new Set<string>(['gemini_vision', 'googlecloud']);
export const WEB_TRANSLATION_ENGINES = new Set<string>(['freegoogle', 'googlecloud', 'llm']);
