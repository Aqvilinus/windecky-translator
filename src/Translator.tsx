import { toaster } from "@decky/api";
import { BackendError, backend } from "./backend";
import { TextRecognizer } from "./TextRecognizer";
import { TextTranslator } from "./TextTranslator";
import { ImageState } from "./Overlay";
import { logger } from "./log";
import { OCR_ENGINE_LABELS, TRANSLATION_ENGINE_LABELS } from "./providers";

const NO_TEXT_MESSAGE_MS = 2000;
const ERROR_MESSAGE_MS = 3000;

export class GameTranslatorLogic {
    private isProcessing = false;
    public imageState: ImageState;
    private textRecognizer: TextRecognizer;
    private textTranslator: TextTranslator;
    private enabled: boolean = true;  // until SettingsContext loads the setting
    private currentRunId: number = 0;

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
        if (this.isProcessing || !this.enabled) {
            logger.debug('Translator', 'Already processing a screenshot or plugin disabled, skipping');
            return;
        }

        if (!this.canStartTranslation()) return;

        const runId = ++this.currentRunId;
        const isCancelled = (): boolean => runId !== this.currentRunId;

        try {
            this.isProcessing = true;

            // before the overlay opens, so it isn't captured
            logger.info('Translator', 'Capturing the screen');
            const capture = await backend.captureScreen();

            if (isCancelled()) {
                logger.debug('Translator', 'Translation cancelled before screenshot processed');
                if (capture.id) backend.discardCapture(capture.id).catch(() => { /* best effort */ });
                return;
            }

            if (!capture.id) {
                logger.warn('Translator', 'Screenshot capture failed, not opening overlay');
                this.notify('Screen capture failed', 4000, capture.error || 'Try pressing the shortcut again');
                return;
            }


            const recognizingStep = this.ocrProvider === 'gemini_vision'
                ? "Recognizing and Translating"
                : "Recognizing";
            this.imageState.startLoading(recognizingStep, this.ocrMethodHint());

            const textRegions = await this.textRecognizer.recognizeCapture(capture.id);
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
                this.imageState.updateProcessingStep("No text found");
                setTimeout(() => {
                    if (!isCancelled()) this.imageState.hide();
                }, NO_TEXT_MESSAGE_MS);
            }
        } catch (error) {
            if (isCancelled()) {
                logger.debug('Translator', 'Translation cancelled, suppressing error UI', error);
                return;
            }

            logger.error('Translator', 'Screenshot and translation error', error);

            // Every failure is shown on the overlay for a moment: the backend's reason, or a generic one
            let message = "Translation failed";
            if (error instanceof BackendError) message = error.message;
            this.imageState.updateProcessingStep(message, true);
            setTimeout(() => {
                if (!isCancelled()) this.imageState.hide();
            }, ERROR_MESSAGE_MS);
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

    setOcrProvider = (provider: string): void => {
        this.ocrProvider = provider;
        logger.debug('Translator', `OCR provider set to: ${provider}`);
    }

    setTranslationProvider = (provider: string): void => {
        this.translationProvider = provider;
        logger.debug('Translator', `Translation provider set to: ${provider}`);
    }

    private translationMethodHint(): string {
        return (TRANSLATION_ENGINE_LABELS as Record<string, string>)[this.translationProvider] || this.translationProvider;
    }

    private ocrMethodHint(): string {
        return (OCR_ENGINE_LABELS as Record<string, string>)[this.ocrProvider] || this.ocrProvider;
    }

    setHasGoogleApiKey = (hasKey: boolean): void => {
        this.hasGoogleApiKey = hasKey;
        logger.debug('Translator', `Google API key available: ${hasKey}`);
    }

    setHasGeminiApiKey = (hasKey: boolean): void => {
        this.hasGeminiApiKey = hasKey;
        logger.debug('Translator', `Gemini API key available: ${hasKey}`);
    }

    // A check that fails shows a toast saying what to set.
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
