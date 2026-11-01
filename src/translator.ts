// Ctrl+Alt+T's work: capture the game, recognize its text, translate it and show it on the overlay
import { toaster } from "@decky/api";
import { BackendError, backend, throwIfBackendError } from "./backend";
import { OverlayStore } from "./overlay";
import { logger } from "./log";
import { OCR_PROVIDER_LABELS, TRANSLATION_PROVIDER_LABELS } from "./providers";
import { TranslatedRegion, filterUntranslatable, mergeRegions } from "./regions";

// The translate/close hotkey (py_modules/windows/hotkey.py HOTKEY)
export const HOTKEY = 'Ctrl+Alt+T';

const MESSAGE_MS = 3000;  // "No text found" and errors on the overlay

// The settings a translation needs (settings.tsx gives them all)
export interface TranslatorSettings {
    enabled: boolean;
    sourceLanguage: string;
    targetLanguage: string;
    ocrProvider: string;
    translationProvider: string;
    googleApiKey: string;
    geminiApiKey: string;
    debugMode: boolean;
    fontScale: number;
}

function toast(title: string, body: string, duration: number): void {
    toaster.toast({ title, body, duration, critical: true });
}

export class Translator {
    readonly overlay: OverlayStore;
    private settings: TranslatorSettings | null = null;  // until loaded from the backend
    private isProcessing = false;
    private currentRunId = 0;

    constructor(overlay: OverlayStore) {
        this.overlay = overlay;
    }

    applySettings(settings: TranslatorSettings): void {
        this.settings = settings;
        logger.setDebugEnabled(settings.debugMode);
        this.overlay.setFontScale(settings.fontScale);
        if (!settings.enabled) this.dismiss();  // the backend frees Ctrl+Alt+T
    }

    dismiss = (): void => {
        this.currentRunId++;
        this.isProcessing = false;
        if (this.overlay.isVisible()) this.overlay.hide();
    }

    translateScreen = async (): Promise<void> => {
        const s = this.settings;
        if (!s?.enabled || this.isProcessing) {
            logger.debug('Translator', 'Already translating, or the plugin is off: skipping');
            return;
        }
        if (!this.canStartTranslation(s)) return;

        const runId = ++this.currentRunId;
        const isCancelled = (): boolean => runId !== this.currentRunId;

        try {
            this.isProcessing = true;

            // before the overlay opens, so it isn't captured
            logger.info('Translator', 'Capturing the screen');
            const capture = await backend.captureScreen();
            if (isCancelled()) {
                if (capture.id) backend.discardCapture(capture.id).catch(() => { /* best effort */ });
                return;
            }
            if (!capture.id) {
                logger.warn('Translator', 'Screenshot capture failed, not opening overlay');
                toast('Screen capture failed', capture.error || 'Try pressing the shortcut again', 4000);
                return;
            }

            this.overlay.showLoading(s.ocrProvider === 'gemini_vision' ? "Recognizing and Translating" : "Recognizing",
                                      OCR_PROVIDER_LABELS[s.ocrProvider as keyof typeof OCR_PROVIDER_LABELS] || s.ocrProvider);
            const recognized = throwIfBackendError(await backend.recognizeCapture(capture.id)) || [];
            const regions = filterUntranslatable(mergeRegions(recognized));
            logger.info('Translator', `${recognized.length} OCR regions, ${regions.length} to translate`);
            if (isCancelled()) return;

            if (regions.length === 0) {
                this.overlay.setStatus("No text found");
                setTimeout(() => {
                    if (!isCancelled()) this.overlay.hide();
                }, MESSAGE_MS);
                return;
            }

            if (!regions.every(r => r.translatedText)) {
                this.overlay.setStatus("Translating text", false,
                    TRANSLATION_PROVIDER_LABELS[s.translationProvider as keyof typeof TRANSLATION_PROVIDER_LABELS]
                    || s.translationProvider);
            }
            const translated: TranslatedRegion[] | null = throwIfBackendError(
                await backend.translateText(regions, s.targetLanguage, s.sourceLanguage));
            if (!translated) throw new BackendError("Translation failed (details in the plugin log)");
            if (isCancelled()) return;

            // A translation that only repeats the original (a name, a number) would just cover it
            this.overlay.showTranslations(translated.filter(r =>
                r.translatedText.trim().toLowerCase() !== r.text.trim().toLowerCase()));
        } catch (error) {
            if (isCancelled()) return;
            logger.error('Translator', 'Screenshot and translation error', error);
            // Every failure is shown on the overlay for a moment: the backend's reason, or a generic one
            this.overlay.setStatus(error instanceof BackendError ? error.message : "Translation failed", true);
            setTimeout(() => {
                if (!isCancelled()) this.overlay.hide();
            }, MESSAGE_MS);
        } finally {
            if (!isCancelled()) this.isProcessing = false;
        }
    }

    // A check that fails shows a toast saying what to set
    private canStartTranslation(s: TranslatorSettings): boolean {
        const problem = !s.sourceLanguage && !s.targetLanguage ? "Input and output languages are not set"
            : !s.sourceLanguage ? "Input language is not set"
            : !s.targetLanguage ? "Output language is not set"
            : null;
        if (problem) {
            toast(problem, `Please select ${s.sourceLanguage || s.targetLanguage ? "it" : "them"} in the plugin settings`, 3000);
            return false;
        }
        if (s.sourceLanguage !== 'auto' && s.sourceLanguage === s.targetLanguage) {
            toast("Input and output languages can't be the same", "Change one of them in the plugin settings", 3000);
            return false;
        }
        const missingKey = this.missingKeyMessage(s);
        if (missingKey) {
            toast(missingKey, "Please configure your API key in the Translation settings tab.", 3000);
            return false;
        }
        return true;
    }

    private missingKeyMessage(s: TranslatorSettings): string | null {
        if (s.ocrProvider === 'gemini_vision' && !s.geminiApiKey) return "Gemini API key required for Gemini Vision";
        if (s.googleApiKey) return null;
        const ocr = s.ocrProvider === 'google_cloud', translation = s.translationProvider === 'google_cloud';
        if (ocr && translation) return "API key required for OCR & Translation";
        if (ocr) return "API key required for OCR";
        if (translation) return "API key required for Translation";
        return null;
    }
}
