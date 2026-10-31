// Overlay.tsx - the translation overlay's state. The backend draws it over the game window
// (py_modules/winport/overlay.py); src/windows.ts forwards every change there.

import { TranslatedRegion } from "./TextTranslator";

// What the backend draws (main.py native_overlay_update -> winport/overlay.py render)
export interface OverlayState {
    visible: boolean;
    regions: TranslatedRegion[];
    loading: boolean;
    processingStep: string;      // the status pill while loading, or the error shown
    processingDetail: string;    // the engine in use, under the step
    processingIsError: boolean;
    fontScale: number;
}

type Listener = (state: OverlayState) => void;

const HIDDEN: Omit<OverlayState, 'fontScale'> = {
    visible: false, regions: [], loading: false, processingStep: "", processingDetail: "", processingIsError: false,
};

export class ImageState {
    private state: OverlayState = { ...HIDDEN, fontScale: 1.0 };
    private listeners = new Set<Listener>();
    private notifyQueued = false;

    // listener(state) after every change; changes made in one go (start of a translation) arrive once, so the
    // backend redraws the screen once. Returns the unsubscribe function.
    subscribe(listener: Listener): () => void {
        this.listeners.add(listener);
        return () => { this.listeners.delete(listener); };
    }

    isVisible(): boolean {
        return this.state.visible;
    }

    // Show the overlay with a status pill
    startLoading(step: string, detail: string = ""): void {
        this.update({ visible: true, regions: [], loading: true, processingStep: step, processingDetail: detail,
                      processingIsError: false });
    }

    updateProcessingStep(step: string, isError: boolean = false, detail: string = ""): void {
        this.update({ loading: true, processingStep: step, processingDetail: detail, processingIsError: isError });
    }

    showTranslations(regions: TranslatedRegion[]): void {
        this.update({ ...HIDDEN, visible: true, regions });
    }

    hide(): void {
        this.update(HIDDEN);
    }

    setFontScale(fontScale: number): void {
        this.update({ fontScale });
    }

    private update(change: Partial<OverlayState>): void {
        this.state = { ...this.state, ...change };
        if (this.notifyQueued) return;
        this.notifyQueued = true;
        queueMicrotask(() => {
            this.notifyQueued = false;
            for (const listener of this.listeners) listener(this.state);
        });
    }
}
