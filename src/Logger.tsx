export enum LogLevel {
    DEBUG = 'DEBUG',
    INFO = 'INFO',
    WARN = 'WARN',
    ERROR = 'ERROR'
}

class Logger {
    private readonly appName = 'WinDeckyTranslator';
    private _enabled = false;

    private readonly styles = {
        appName: 'color: #ff69b4; font-weight: bold;',
        debug: 'color: #00bfff;',
        info: 'color: #00ff00;',
        warn: 'color: #ffa500;',
        error: 'color: #ff0000; font-weight: bold;',
        reset: 'color: inherit;'
    };

    setEnabled(enabled: boolean): void {
        this._enabled = enabled;
        if (enabled) {
            console.log(
                `%c${this.appName}%c | %cINFO%c | Logger | Debug logging enabled`,
                this.styles.appName,
                this.styles.reset,
                this.styles.info,
                this.styles.reset
            );
        }
    }

    private log(level: LogLevel, component: string, message: string, ...args: any[]): void {
        if (!this._enabled && level !== LogLevel.ERROR) {
            return;
        }

        const levelStyle = this.styles[level.toLowerCase() as keyof typeof this.styles] || this.styles.info;

        console.log(
            `%c${this.appName}%c | %c${level}%c | ${component} | ${message}`,
            this.styles.appName,
            this.styles.reset,
            levelStyle,
            this.styles.reset,
            ...args
        );
    }

    debug(component: string, message: string, ...args: any[]): void {
        this.log(LogLevel.DEBUG, component, message, ...args);
    }

    info(component: string, message: string, ...args: any[]): void {
        this.log(LogLevel.INFO, component, message, ...args);
    }

    warn(component: string, message: string, ...args: any[]): void {
        this.log(LogLevel.WARN, component, message, ...args);
    }

    error(component: string, message: string, ...args: any[]): void {
        this.log(LogLevel.ERROR, component, message, ...args);
    }

    logObject(component: string, label: string, obj: any): void {
        if (!this._enabled) {
            return;
        }

        console.log(
            `%c${this.appName}%c | %cDEBUG%c | ${component} | ${label}:`,
            this.styles.appName,
            this.styles.reset,
            this.styles.debug,
            this.styles.reset,
            obj
        );
    }
}

export const logger = new Logger();
