// The frontend's log in Steam's CEF console: errors always, the rest with the Debug Mode setting
let debugEnabled = false;

const write = (out: (...args: any[]) => void, always: boolean) =>
    (component: string, message: string, ...args: any[]): void => {
        if (always || debugEnabled) out(`WinDeckyTranslator | ${component} | ${message}`, ...args);
    };

export const logger = {
    setDebugEnabled(enabled: boolean): void { debugEnabled = enabled; },
    debug: write(console.debug, false),
    info: write(console.info, false),
    warn: write(console.warn, false),
    error: write(console.error, true),
};
