// Every call into the backend (main.py, the Plugin class's async methods), typed in one place. A method the frontend
// calls must exist in main.py: tests/frontend/backendContract.test.ts checks this list against it.
import { callable } from "@decky/api";
import type { OverlayState } from "./Overlay";
import type { TextRegion, TranslatedRegion } from "./regions";

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

// A failure the backend reported as {error: code, message} (main.py catch_errors): the message is shown on the overlay
export interface ErrorResponse { error: string; message: string }
export class BackendError extends Error {}

// A backend reply that reports a failure as a BackendError; any other reply passes through
export function throwIfBackendError<T>(response: T | ErrorResponse): T {
    if (typeof response === 'object' && response !== null && 'error' in response && 'message' in response) {
        throw new BackendError(response.message);
    }
    return response as T;
}

export const backend = {
    getAllSettings: callable<[], BackendSettings>('get_all_settings'),
    setSetting: callable<[key: string, value: unknown], boolean>('set_setting'),
    getClipboardText: callable<[], string>('get_clipboard_text'),
    // the pixels stay in the backend; the frontend gets the capture's id, or why nothing was captured
    captureScreen: callable<[], { id?: number; error?: string }>('capture_screen'),
    discardCapture: callable<[id: number], boolean>('discard_capture'),
    recognizeCapture: callable<[id: number], TextRegion[] | ErrorResponse>('recognize_capture'),
    translateText: callable<[regions: TextRegion[], target: string, input: string],
        TranslatedRegion[] | ErrorResponse | null>('translate_text'),
    updateOverlay: callable<[state: Partial<OverlayState>], boolean>('update_overlay'),
    getStartupErrors: callable<[], string[]>('get_startup_errors'),
    checkWebReachability: callable<[],
        { ocr?: Reachability | null; translation?: Reachability | null; error?: string }>('check_web_reachability'),
    getDiagnostics: callable<[], Record<string, any>>('get_diagnostics'),
    getWindowsOcrLanguages: callable<[], string[]>('get_windows_ocr_languages'),
    getGeminiModels: callable<[], string[]>('get_gemini_models'),
    getLlmModels: callable<[backend: string], string[]>('get_llm_models'),
    getModelStatus: callable<[kind: ModelKind], ModelStatus | null>('get_model_status'),
    downloadModel: callable<[kind: ModelKind], boolean>('download_model'),
    cancelModelDownload: callable<[kind: ModelKind], void>('cancel_model_download'),
    clearModelError: callable<[kind: ModelKind], void>('clear_model_error'),
    deleteModel: callable<[kind: ModelKind], boolean>('delete_model'),
    countTranslationCacheEntries: callable<[], number>('count_translation_cache_entries'),
    getTranslationCacheEntries: callable<[limit: number], any[]>('get_translation_cache_entries'),
    deleteTranslationCacheEntry: callable<[sourceLang: string, targetLang: string, source: string],
        void>('delete_translation_cache_entry'),
    clearTranslationCache: callable<[], void>('clear_translation_cache'),
};
