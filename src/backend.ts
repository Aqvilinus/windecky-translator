// Every call into the backend (main.py, the Plugin class's async methods), typed in one place. A method the frontend
// calls must exist in main.py: tests/frontend/backendContract.test.ts checks this list against it.
import { callable } from "@decky/api";
import type { ErrorResponse } from "./errors";
import type { OverlayState } from "./Overlay";
import type { TextRegion } from "./TextRecognizer";
import type { TranslatedRegion } from "./TextTranslator";

// main.py SETTING_DEFAULTS, keys as the backend names them
export type BackendSettings = Record<string, any>;
// A downloadable model: offline translation, on-device OCR
export type ModelKind = 'nllb' | 'chromescreenai';
export interface ModelStatus {
    downloaded: boolean;
    size: number;
    approx_size_mb: number;
    downloading: boolean;
    progress: number;
    error: string | null;
}
export interface Reachability { ok: boolean; reason: string; provider: string }

export const backend = {
    // settings
    getAllSettings: callable<[], BackendSettings>('get_all_settings'),
    setSetting: callable<[key: string, value: unknown], boolean>('set_setting'),
    getClipboardText: callable<[], string>('get_clipboard_text'),
    // the translation
    // the capture's name for recognize_text_file ("" when nothing was captured); the pixels stay in the backend
    takeScreenshot: callable<[appName: string], { path: string }>('take_screenshot'),
    discardScreenshot: callable<[path: string], boolean>('discard_screenshot'),
    recognizeTextFile: callable<[path: string], TextRegion[] | ErrorResponse>('recognize_text_file'),
    translateText: callable<[regions: TextRegion[], target: string, input: string],
        TranslatedRegion[] | ErrorResponse | null>('translate_text'),
    nativeOverlayUpdate: callable<[state: Partial<OverlayState>], boolean>('native_overlay_update'),
    // status
    getBootStatus: callable<[], string[]>('get_boot_status'),
    getProviderStatus: callable<[], Record<string, any>>('get_provider_status'),
    checkWebReachability: callable<[],
        { ocr?: Reachability | null; translation?: Reachability | null; error?: string }>('check_web_reachability'),
    getWindowsStatus: callable<[], Record<string, any>>('get_windows_status'),
    getWindowsOcrLanguages: callable<[], string[]>('get_windows_ocr_languages'),
    // model lists for the pickers
    getGeminiModels: callable<[], string[]>('get_gemini_models'),
    getLlmModels: callable<[backend: string], string[]>('get_llm_models'),
    // downloadable models
    getModelStatus: callable<[kind: ModelKind], ModelStatus | null>('get_model_status'),
    downloadModel: callable<[kind: ModelKind], boolean>('download_model'),
    cancelModelDownload: callable<[kind: ModelKind], void>('cancel_model_download'),
    clearModelError: callable<[kind: ModelKind], void>('clear_model_error'),
    deleteModel: callable<[kind: ModelKind], boolean>('delete_model'),
    // translation cache
    getTranslationCacheStats: callable<[], { entries: number; hits: number; size_bytes: number }>(
        'get_translation_cache_stats'),
    getTranslationCacheEntries: callable<[limit: number], any[]>('get_translation_cache_entries'),
    deleteTranslationCacheEntry: callable<[sourceLang: string, targetLang: string, source: string],
        { success: boolean }>('delete_translation_cache_entry'),
    clearTranslationCache: callable<[], { success: boolean; cleared?: number }>('clear_translation_cache'),
};
