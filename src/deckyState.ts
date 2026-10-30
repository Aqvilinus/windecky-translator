// Decky Loader remembers the plugin open in the side menu as an object (deckyState._activePlugin) and keeps that
// object when the plugin is reloaded (a store update, a disable/enable): the side menu then goes on showing the
// unloaded instance. Its Translate still translated, but onDismount had cut its overlay off, so nothing appeared and
// its button stayed on "Close Overlay" until the menu was navigated away from the plugin. Once this instance is
// registered, point Decky at it.

export interface DeckyPluginEntry {
    name: string;
    content?: unknown;
}

interface DeckyStateLike {
    _activePlugin?: DeckyPluginEntry | null;
    _plugins?: DeckyPluginEntry[];
    setActivePlugin?(name: string): void;
}

const CHECK_MS = 100;
const GIVE_UP_MS = 10000;

function deckyState(): DeckyStateLike | undefined {
    try {
        return (window as unknown as { DeckyPluginLoader?: { deckyState?: DeckyStateLike } }).DeckyPluginLoader?.deckyState;
    } catch {
        return undefined;
    }
}

// Returns a function that stops waiting (for onDismount).
export function adoptActivePlugin(name: string, isThisInstance: (plugin: DeckyPluginEntry) => boolean): () => void {
    const started = Date.now();
    const timer = setInterval(() => {
        const state = deckyState();
        const current = state?._plugins?.find(p => p.name === name);
        if (current && isThisInstance(current)) {
            clearInterval(timer);
            const active = state?._activePlugin;
            if (active && active.name === name && active !== current) state?.setActivePlugin?.(name);
        } else if (Date.now() - started > GIVE_UP_MS) {
            clearInterval(timer);
        }
    }, CHECK_MS);
    return () => clearInterval(timer);
}
