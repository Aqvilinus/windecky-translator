// Every backend method the frontend calls must exist in main.py (a method removed from one side only fails silently
// in the game: the call's error is swallowed and the feature just stops working).
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const root = join(__dirname, '..', '..');

function sourceFiles(dir: string): string[] {
    return readdirSync(dir).flatMap(name => {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) return sourceFiles(path);
        return /\.tsx?$/.test(name) ? [path] : [];
    });
}

const frontendCalls = new Set<string>();
for (const file of sourceFiles(join(root, 'src'))) {
    for (const m of readFileSync(file, 'utf8').matchAll(/\bcall\s*(?:<[^>]*>)?\(\s*['"]([A-Za-z_]\w*)['"]/g)) {
        frontendCalls.add(m[1]);
    }
}
const backendMethods = new Set(
    [...readFileSync(join(root, 'main.py'), 'utf8').matchAll(/^ {4}async def ([A-Za-z_]\w*)\(/gm)].map(m => m[1]),
);

describe('frontend -> backend calls', () => {
    it('finds the calls', () => {
        expect(frontendCalls.size).toBeGreaterThan(20);
        expect(frontendCalls).toContain('native_overlay_update');
    });

    it.each([...frontendCalls].sort())('%s exists in main.py', name => {
        expect(backendMethods).toContain(name);
    });
});
