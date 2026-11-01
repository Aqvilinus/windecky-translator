// TextTranslator.tsx

import { backend } from "./backend";
import { TextRegion } from "./TextRecognizer";
import { BackendError, throwIfBackendError } from "./errors";

// Include translated text with the original region info
export interface TranslatedRegion extends TextRegion {
    translatedText: string;
}

export class TextTranslator {
    private targetLanguage: string;
    private inputLanguage: string = "auto"; // Default to auto-detect

    constructor(initialLanguage: string = "en") {
        this.targetLanguage = initialLanguage;
    }

    setTargetLanguage(language: string): void {
        this.targetLanguage = language;
    }

    getTargetLanguage(): string {
        return this.targetLanguage;
    }

    // New methods for input language
    setInputLanguage(language: string): void {
        this.inputLanguage = language;
    }

    getInputLanguage(): string {
        return this.inputLanguage;
    }

    async translateText(textRegions: TextRegion[]): Promise<TranslatedRegion[]> {
        if (!textRegions.length) return [];
        const translated = throwIfBackendError(
            await backend.translateText(textRegions, this.targetLanguage, this.inputLanguage));
        if (!translated) throw new BackendError("Translation failed (details in the plugin log)");
        return translated;
    }
}