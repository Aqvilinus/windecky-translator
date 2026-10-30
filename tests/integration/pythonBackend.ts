// The real main.py behind the emulated Decky (python_backend.py runs it, with the Windows parts and the network
// stubbed as in tests/backend). PLUGIN_PYTHON names the Python that has requirements-windows.txt and
// requirements-dev.txt installed; the contract tests are skipped without it.
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import type { Backend } from './decky';

export const PYTHON = process.env.PLUGIN_PYTHON;

export interface WindowsState {
    captures: number;
    overlay: { visible: boolean; shows: number; hides: number; regions: any[] | null } | null;
    hotkey: { enabled: boolean; holds: [boolean, string][] } | null;
    suspended: number[];
}

export class PythonBackend implements Backend {
    readonly errors: string[] = [];
    private proc!: ChildProcessWithoutNullStreams;
    private pending = new Map<number, { resolve(v: unknown): void; reject(e: Error): void }>();
    private nextId = 1;
    stderr = '';

    async start() {
        if (!PYTHON) throw new Error('PLUGIN_PYTHON is not set');
        this.proc = spawn(PYTHON, [join(__dirname, 'python_backend.py')], { env: { ...process.env, PYTHONUTF8: '1' } });
        this.proc.stderr.on('data', d => { this.stderr += d; });
        const lines = createInterface({ input: this.proc.stdout });
        const ready = new Promise<void>((resolve, reject) => {
            this.proc.once('exit', code => reject(new Error(`python_backend.py exited (${code}):\n${this.stderr}`)));
            lines.on('line', line => {
                const msg = JSON.parse(line);
                if (msg.ready) return resolve();
                const p = this.pending.get(msg.id);
                this.pending.delete(msg.id);
                if (!p) return;
                if ('error' in msg) p.reject(new Error(msg.error));
                else p.resolve(msg.result);
            });
        });
        await ready;
        return this;
    }

    private send(method: string, args: unknown[]): Promise<unknown> {
        const id = this.nextId++;
        return new Promise((resolve, reject) => {
            this.pending.set(id, { resolve, reject });
            this.proc.stdin.write(JSON.stringify({ id, method, args }) + '\n');
        });
    }

    async call(method: string, args: unknown[]) {
        try {
            return await this.send(method, args);
        } catch (e) {
            this.errors.push(`${method}: ${(e as Error).message}`);
            throw e;
        }
    }

    async restart() { await this.send('__restart__', []); }

    windows() { return this.send('__windows__', []) as Promise<WindowsState>; }

    stop() {
        this.proc?.stdin.end();
        this.proc?.kill();
    }
}
