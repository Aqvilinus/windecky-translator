// A scripted stand-in for main.py: answers like the real backend does on Windows (shapes from main.py), keeps the
// settings in memory, and fails loudly on a method it doesn't know (the real Decky rejects the call too, and the
// plugin would silently lose that feature). tests/integration/pythonBackend.ts puts the real main.py here instead.
import type { Backend } from './decky';

export interface Region {
    text: string;
    rect: { left: number; top: number; right: number; bottom: number };
    confidence: number;
    isDialog: boolean;
    translatedText?: string;
}

// The OCR result of the emulated game screen, and its translation
export const SCREEN_TEXT: Region[] = [
    { text: 'Willkommen, Reisender', rect: { left: 40, top: 40, right: 420, bottom: 80 }, confidence: 0.98, isDialog: false },
    { text: 'Neues Spiel', rect: { left: 40, top: 120, right: 260, bottom: 150 }, confidence: 0.97, isDialog: false },
];
export const DICTIONARY: Record<string, string> = {
    'Willkommen, Reisender': 'Welcome, traveller',
    'Neues Spiel': 'New game',
};

// main.py PLACEHOLDER_PNG_BASE64: on Windows the screenshot stays in the backend
const PLACEHOLDER_PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==';

type Handler = (...args: any[]) => unknown;

export class FakeBackend implements Backend {
    readonly unknownCalls: string[] = [];
    restarts = 0;
    settings: Record<string, unknown> = {
        enabled: true, target_language: 'en', input_language: 'auto', input_mode: 0,
        ocr_provider: 'windows_ocr', translation_provider: 'freegoogle', use_free_providers: true,
        hold_time_translate: 1000, hold_time_dismiss: 500, confidence_threshold: 0.6,
        pause_game_on_overlay: false, quick_toggle_enabled: false, debug_mode: false, font_scale: 1.0,
        translated_text_alignment: 'auto', translation_cache_enabled: true, google_api_key: '', gemini_api_key: '',
    };
    screenshots = 0;

    readonly handlers: Record<string, Handler> = {
        get_all_settings: () => ({ ...this.settings }),
        get_setting: (key: string, dflt: unknown) => this.settings[key] ?? dflt,
        set_setting: (key: string, value: unknown) => { this.settings[key] = value; return true; },
        get_enabled_state: () => this.settings.enabled,
        get_provider_status: () => ({
            ocr_provider_preference: this.settings.ocr_provider, translation_provider_preference: this.settings.translation_provider,
            ocr_provider: 'Windows OCR', translation_provider: 'Free Google Translate', ocr_available: true,
            translation_available: true, nllb_downloaded: false, chromescreenai_downloaded: false, rapidocr_downloaded: false,
        }),
        check_web_reachability: () => ({ ocr: null, translation: { ok: true, reason: '', provider: 'freegoogle' } }),
        take_screenshot: (appName: string) => ({
            path: `C:\\Temp\\decky-translator\\${appName || 'Decky-Screenshot'}_${++this.screenshots}.png`,
            base64: PLACEHOLDER_PNG,
        }),
        discard_screenshot: () => true,
        recognize_text_file: () => SCREEN_TEXT.map(r => ({ ...r })),
        translate_text: (regions: Region[]) => regions.map(r => ({ ...r, translatedText: DICTIONARY[r.text] ?? r.text })),
        native_overlay_update: () => true,
        set_steam_app: () => true,
        get_windows_status: () => ({ hotkey: { registered: true }, capture: {} }),
        get_boot_status: () => [],  // no problems while loading
        get_windows_ocr_languages: () => ['en', 'de'],
        get_translation_cache_stats: () => ({ entries: 0, size_bytes: 0 }),
        start_hidraw_monitor: () => ({ success: false, error: 'No controller shortcut on Windows' }),
        stop_hidraw_monitor: () => ({ success: true, message: 'Monitor stopped' }),
    };

    async call(method: string, args: unknown[]) {
        const handler = this.handlers[method];
        if (!handler) {
            this.unknownCalls.push(method);
            throw new Error(`fake backend: no method ${method}`);
        }
        return handler(...args);
    }

    async restart() { this.restarts++; }
}
