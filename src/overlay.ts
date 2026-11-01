// The translation overlay's state, and its way to the backend. On SteamOS gamescope keeps Steam's UI, and with it the
// overlay, above the game; on Windows Big Picture is a normal window behind the game, so the backend draws the
// overlay in a click-through window of its own (py_modules/overlay.py).
import { backend } from "./backend";
import { TranslatedRegion } from "./regions";
import { isAnySideMenuOpen } from "./steam";

const SIDE_MENU_CHECK_MS = 250;

// What the backend draws (main.py update_overlay -> overlay.py render)
export interface OverlayState {
    visible: boolean;
    regions: TranslatedRegion[];
    loading: boolean;
    status: string;      // the status pill while loading, or the error shown
    statusDetail: string;    // the engine in use, under the step
    isError: boolean;
    fontScale: number;
}

type Listener = (state: OverlayState) => void;

const HIDDEN: Omit<OverlayState, 'fontScale'> = {
    visible: false, regions: [], loading: false, status: "", statusDetail: "", isError: false,
};

export class OverlayStore {
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

    showLoading(step: string, detail: string = ""): void {
        this.update({ visible: true, regions: [], loading: true, status: step, statusDetail: detail,
                      isError: false });
    }

    setStatus(step: string, isError: boolean = false, detail: string = ""): void {
        this.update({ loading: true, status: step, statusDetail: detail, isError: isError });
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

// Every change to the backend, which draws it; the screenshot stays in the backend, which took it
export function forwardOverlayToBackend(store: OverlayStore, dismiss: () => void): () => void {
    let menuTimer: ReturnType<typeof setInterval> | null = null;
    let menuOpen = false;
    const stopWatchingMenus = () => {
        if (menuTimer) clearInterval(menuTimer);
        menuTimer = null;
        menuOpen = false;
    };
    // The side menu over a game is drawn into the game's window, under the overlay window: opening one closes the
    // translation. A menu still open when the translation appears (closing after Translate) doesn't count.
    const watchMenus = () => {
        if (menuTimer) return;
        menuOpen = isAnySideMenuOpen();
        menuTimer = setInterval(() => {
            const open = isAnySideMenuOpen();
            const opened = open && !menuOpen;
            menuOpen = open;
            if (opened) dismiss();
        }, SIDE_MENU_CHECK_MS);
    };

    const unsubscribe = store.subscribe((s: OverlayState) => {
        if (s.visible) watchMenus(); else stopWatchingMenus();
        backend.updateOverlay(s).catch(() => { /* the backend logs its own errors */ });
    });
    return () => {
        stopWatchingMenus();
        unsubscribe();
    };
}
