import { backend } from "./backend";
import { TextRegion } from "./TextRecognizer";
import { BackendError, throwIfBackendError } from "./backend";

export interface TranslatedRegion extends TextRegion {
    translatedText: string;
}

export class TextTranslator {
    private targetLanguage: string;
    private inputLanguage: string = "auto";

    constructor() {
        this.targetLanguage = "en";
    }

    setTargetLanguage(language: string): void {
        this.targetLanguage = language;
    }

    getTargetLanguage(): string {
        return this.targetLanguage;
    }

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