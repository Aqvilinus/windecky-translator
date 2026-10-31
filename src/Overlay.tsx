// Overlay.tsx - the translation overlay's state. The backend draws it over the game window
// (py_modules/winport/overlay.py); src/windows.ts forwards every change there.

import { TranslatedRegion } from "./TextTranslator";
import { logger } from "./Logger";

type StateListener = (visible: boolean, imageData: string, regions: TranslatedRegion[], loading: boolean,
                      processingStep: string, processingDetail: string, processingIsError: boolean,
                      translationsVisible: boolean, fontScale: number) => void;

// Enhanced ImageState to handle translated text regions
export class ImageState {
    private visible = false;
    private imageData = "";
    private translatedRegions: TranslatedRegion[] = [];
    private loading = false;
    private processingStep = ""; // Added to track current processing step
    private processingDetail = "";
    private processingIsError = false;
    private loadingIndicatorTimer: ReturnType<typeof setTimeout> | null = null; // Timer for delayed indicator
    private translationsVisible = true; // New property to track translation visibility
    private fontScale = 1.0;
    private onStateChangedListeners: StateListener[] = [];

    onStateChanged(callback: StateListener): void {
        this.onStateChangedListeners.push(callback);
    }

    offStateChanged(callback: StateListener): void {
        const index = this.onStateChangedListeners.indexOf(callback);
        if (index !== -1) {
            this.onStateChangedListeners.splice(index, 1);
        }
    }

    // Show the overlay with loading indicator immediately
    startLoading(step: string = "Capturing"): void {
        // Set internal state immediately
        this.visible = true;
        this.loading = true;
        this.processingStep = step;
        this.processingDetail = "";
        this.processingIsError = false;
        this.translationsVisible = true; // Reset to visible when starting new translation

        // Clear any existing timer
        if (this.loadingIndicatorTimer) {
            clearTimeout(this.loadingIndicatorTimer);
            this.loadingIndicatorTimer = null;
        }

        // Show loading indicator immediately - no stealth mode
        // This ensures the overlay has visible content which properly maintains UI composition
        this.notifyListeners();
    }

    setFontScale(scale: number): void {
        this.fontScale = scale;
        this.notifyListeners();
    }

    // Update the current processing step
    updateProcessingStep(step: string, isError: boolean = false, detail: string = ""): void {
        this.processingStep = step;
        this.processingDetail = detail;
        this.processingIsError = isError;
        // Update the loading state and keep the current image displayed
        this.loading = true;
        // Force immediate update
        this.notifyListeners();
    }

    showImage(imageData: string): void {
        // Clear any pending timer
        if (this.loadingIndicatorTimer) {
            clearTimeout(this.loadingIndicatorTimer);
            this.loadingIndicatorTimer = null;
        }

        // Always set a fresh image data - don't reuse old data
        this.imageData = imageData;

        // Clear any previous translations
        this.translatedRegions = [];

        // Ensure the overlay is visible
        this.visible = true;

        // Reset translations visibility to true for new image
        this.translationsVisible = true;

        // Set loading state based on whether we're in the middle of processing
        this.loading = this.processingStep !== "";

        logger.debug('ImageState', `Showing new image, length: ${imageData.length}, loading: ${this.loading}, step: ${this.processingStep}`);

        // Notify all listeners about the state change
        this.notifyListeners();
    }

    showTranslatedImage(imageData: string, regions: TranslatedRegion[]): void {
        // Clear any pending timer
        if (this.loadingIndicatorTimer) {
            clearTimeout(this.loadingIndicatorTimer);
            this.loadingIndicatorTimer = null;
        }

        // Always set fresh image data
        this.imageData = imageData;

        // Set the translated regions
        this.translatedRegions = regions;

        // Ensure the overlay is visible
        this.visible = true;

        // Make sure translations are visible when first showing them
        this.translationsVisible = true;

        // Turn off loading state and clear processing step
        this.loading = false;
        this.processingStep = "";
        this.processingDetail = "";
        this.processingIsError = false;

        logger.info('ImageState', `Showing translated image with ${regions.length} text regions`);

        this.notifyListeners();
    }

    hideImage(): void {
        // Clear any pending timer
        if (this.loadingIndicatorTimer) {
            clearTimeout(this.loadingIndicatorTimer);
            this.loadingIndicatorTimer = null;
        }

        // Reset all state properties
        this.visible = false;
        this.loading = false;
        this.processingStep = "";
        this.processingDetail = "";
        this.processingIsError = false;
        this.translationsVisible = true; // Reset to default when hiding

        // Important: Clear the image data and regions to prevent reuse
        this.imageData = "";
        this.translatedRegions = [];

        logger.debug('ImageState', 'Hiding image and clearing all state');

        this.notifyListeners();
    }

    private notifyListeners(): void {
        for (const callback of this.onStateChangedListeners) {
            callback(this.visible, this.imageData, this.translatedRegions, this.loading, this.processingStep, this.processingDetail, this.processingIsError, this.translationsVisible, this.fontScale);
        }
    }

    isVisible(): boolean {
        return this.visible;
    }
}
