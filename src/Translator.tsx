// Translator.tsx - Handles translator logic and API interactions

import { call, toaster } from "@decky/api";
import { Router } from "@decky/ui";
import { TextRecognizer, BackendError, NetworkError, ApiKeyError } from "./TextRecognizer";
import { TextTranslator } from "./TextTranslator";
import { ImageState } from "./Overlay";
import { logger } from "./Logger";

// main.py take_screenshot: the capture's name for recognize_text_file ("" when nothing was captured); the pixels
// stay in the backend, which draws the overlay
interface ScreenshotResponse {
    path: string;
}

// Main app logic
export class GameTranslatorLogic {
    private isProcessing = false;
    public imageState: ImageState;
    private textRecognizer: TextRecognizer;
    private textTranslator: TextTranslator;
    private enabled: boolean = true;  // until SettingsContext loads the setting
    private currentRunId: number = 0;

    // Provider settings for upfront validation
    private ocrProvider: string = "chromescreenai";
    private translationProvider: string = "freegoogle";
    private hasGoogleApiKey: boolean = false;
    private hasGeminiApiKey: boolean = false;

    isOverlayVisible(): boolean {
        return this.imageState.isVisible();
    }

    constructor(imageState: ImageState) {
        this.imageState = imageState;
        this.textRecognizer = new TextRecognizer();
        this.textTranslator = new TextTranslator();
    }

    // Switch the plugin on or off (SettingsContext saves the setting; the backend frees or takes Ctrl+Alt+T)
    setEnabled(enabled: boolean): void {
        this.enabled = enabled;
        if (!enabled) {
            this.dismiss();
        }
    }

    setConfidenceThreshold(threshold: number): void {
        this.textRecognizer.setConfidenceThreshold(threshold);
    }

    notify = async (message: string, duration: number = 1000, body?: string): Promise<void> => {
        toaster.toast({
            title: message,
            body: body || message,
            duration: duration,
            critical: true
        });
    }

    dismiss = (): void => {
        this.currentRunId++;
        this.isProcessing = false;
        if (this.imageState.isVisible()) {
            this.imageState.hide();
        }
    }

    takeScreenshotAndTranslate = async (): Promise<void> => {
        // If already processing or disabled, return
        if (this.isProcessing || !this.enabled) {
            logger.debug('Translator', 'Already processing a screenshot or plugin disabled, skipping');
            return;
        }

        if (!this.canStartTranslation()) return;

        const runId = ++this.currentRunId;
        const isCancelled = (): boolean => runId !== this.currentRunId;

        try {
            this.isProcessing = true;

            // Take screenshot FIRST while screen is clean (no overlay visible)
            const appName = Router.MainRunningApp?.display_name || "";
            logger.info('Translator', `Taking new screenshot for: ${appName}`);
            const result = await call<[string], ScreenshotResponse>('take_screenshot', appName);

            if (isCancelled()) {
                logger.debug('Translator', 'Translation cancelled before screenshot processed');
                if (result?.path) call('discard_screenshot', result.path).catch(() => { /* best effort */ });
                return;
            }

            if (!result?.path) {
                logger.warn('Translator', 'Screenshot capture failed, not opening overlay');
                this.notify('Screen capture failed', 2500, 'Try pressing the shortcut again');
                return;
            }

            logger.debug('Translator', `Screenshot captured: ${result.path}`);

            const recognizingStep = this.ocrProvider === 'gemini_vision'
                ? "Recognizing and Translating"
                : "Recognizing";
            this.imageState.startLoading(recognizingStep, this.ocrMethodHint());

            const textRegions = await this.textRecognizer.recognizeTextFile(result.path);
            if (isCancelled()) {
                logger.debug('Translator', 'Translation cancelled after OCR');
                return;
            }
            logger.info('Translator', `Found ${textRegions.length} text regions`);

            if (textRegions.length > 0) {
                const alreadyTranslated = textRegions.every(r => r.translatedText);
                if (!alreadyTranslated) {
                    this.imageState.updateProcessingStep("Translating text", false, this.translationMethodHint());
                }

                // Translate text (skips backend call if already translated by OCR provider)
                let translatedRegions = await this.textTranslator.translateText(textRegions);
                if (isCancelled()) {
                    logger.debug('Translator', 'Translation cancelled after translation step');
                    return;
                }
                logger.info('Translator', `Translation complete: ${translatedRegions.length} regions`);

                // A translation that only repeats the original (a name, a number) would just cover it
                const before = translatedRegions.length;
                translatedRegions = translatedRegions.filter(r =>
                    r.translatedText.trim().toLowerCase() !== r.text.trim().toLowerCase()
                );
                if (translatedRegions.length < before) {
                    logger.info('Translator', `Filtered ${before - translatedRegions.length} identical translations`);
                }

                this.imageState.showTranslations(translatedRegions);
            } else {
                // No text found, show message
                this.imageState.updateProcessingStep("No text found");

                // Hide overlay after a short delay
                setTimeout(() => {
                    if (!isCancelled()) this.imageState.hide();
                }, 2000); // 2 seconds delay
            }
        } catch (error) {
            if (isCancelled()) {
                logger.debug('Translator', 'Translation cancelled, suppressing error UI', error);
                return;
            }

            logger.error('Translator', 'Screenshot and translation error', error);

            // Every failure is shown on the overlay for a moment: the backend's reason, or a generic one
            let message = "Translation failed";
            if (error instanceof BackendError && error.message) message = error.message;
            else if (error instanceof NetworkError) message = "No internet connection";
            else if (error instanceof ApiKeyError) message = "Invalid API key";
            const quick = error instanceof NetworkError || error instanceof ApiKeyError;
            this.imageState.updateProcessingStep(message, true);
            setTimeout(() => {
                if (!isCancelled()) this.imageState.hide();
            }, quick ? 2500 : 3000);
        }
        finally {
            if (!isCancelled()) {
                this.isProcessing = false;
            }
        }
    }

    setInputLanguage = (language: string): void => {
        this.textTranslator.setInputLanguage(language);
    }

    getInputLanguage = (): string => {
        return this.textTranslator.getInputLanguage();
    }

    setTargetLanguage = (language: string): void => {
        this.textTranslator.setTargetLanguage(language);
    }

    getTargetLanguage = (): string => {
        return this.textTranslator.getTargetLanguage();
    }

    setFontScale = (scale: number): void => {
        this.imageState.setFontScale(scale);
    }

    // Methods for provider settings (used for upfront API key validation)
    setOcrProvider = (provider: string): void => {
        this.ocrProvider = provider;
        logger.debug('Translator', `OCR provider set to: ${provider}`);
    }

    setTranslationProvider = (provider: string): void => {
        this.translationProvider = provider;
        logger.debug('Translator', `Translation provider set to: ${provider}`);
    }

    private translationMethodHint(): string {
        const labels: Record<string, string> = {
            ct2: "On-Device",
            freegoogle: "Google Translate",
            googlecloud: "Google Cloud",
            llm: "AI",
        };
        return labels[this.translationProvider] || this.translationProvider;
    }

    private ocrMethodHint(): string {
        const labels: Record<string, string> = {
            chromescreenai: "On-Device",
            windows_ocr: "On-Device",
            ocrspace: "OCR.space",
            googlecloud: "Google Cloud",
            gemini_vision: "Gemini Vision",
        };
        return labels[this.ocrProvider] || this.ocrProvider;
    }

    setHasGoogleApiKey = (hasKey: boolean): void => {
        this.hasGoogleApiKey = hasKey;
        logger.debug('Translator', `Google API key available: ${hasKey}`);
    }

    setHasGeminiApiKey = (hasKey: boolean): void => {
        this.hasGeminiApiKey = hasKey;
        logger.debug('Translator', `Gemini API key available: ${hasKey}`);
    }

    // Runs all pre-checks that would prevent a translation from starting.
    // Returns false and shows a toast if any check fails.
    private canStartTranslation(): boolean {
        const inputLang = this.getInputLanguage();
        const targetLang = this.getTargetLanguage();
        if (!inputLang && targetLang) {
            logger.warn('Translator', 'Cannot start translation: languages not configured');
            this.notify("Input language is not set", 3000, "Please select it in the plugin settings");
            return false;
        }
        if (!targetLang && inputLang) {
            logger.warn('Translator', 'Cannot start translation: languages not configured');
            this.notify("Output language is not set", 3000, "Please select it in the plugin settings");
            return false;
        }
        if (!inputLang && !targetLang) {
            logger.warn('Translator', 'Cannot start translation: languages not configured');
            this.notify("Input and output languages are not set", 3000, "Please select them in the plugin settings");
            return false;
        }

        if (inputLang !== 'auto' && inputLang === targetLang) {
            logger.warn('Translator', `Cannot start translation: input and output language are both ${inputLang}`);
            this.notify("Input and output languages can't be the same", 3000, "Change one of them in the plugin settings");
            return false;
        }

        const apiKeyCheck = this.requiresApiKeyButMissing();
        if (apiKeyCheck.missing) {
            logger.warn('Translator', `Cannot start translation: ${apiKeyCheck.message}`);
            this.notify(apiKeyCheck.message, 3000, "Please configure your API key in the Translation settings tab.");
            return false;
        }

        return true;
    }

    // Check if the current provider configuration requires an API key that's missing
    private requiresApiKeyButMissing(): { missing: boolean; message: string } {
        if (this.ocrProvider === 'gemini_vision' && !this.hasGeminiApiKey) {
            return { missing: true, message: "Gemini API key required for Gemini Vision" };
        }

        const ocrNeedsKey = this.ocrProvider === 'googlecloud';
        const translationNeedsKey = this.translationProvider === 'googlecloud';

        if ((ocrNeedsKey || translationNeedsKey) && !this.hasGoogleApiKey) {
            if (ocrNeedsKey && translationNeedsKey) {
                return { missing: true, message: "API key required for OCR & Translation" };
            } else if (ocrNeedsKey) {
                return { missing: true, message: "API key required for OCR" };
            } else {
                return { missing: true, message: "API key required for Translation" };
            }
        }
        return { missing: false, message: "" };
    }
}
