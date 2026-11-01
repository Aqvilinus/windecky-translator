// Every backend method the frontend calls (src/backend.ts) must exist in main.py: a method removed from one side
// only fails in the game, where the call's error is swallowed and the feature just stops working.
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const root = join(__dirname, '..', '..');
const frontendCalls = [...readFileSync(join(root, 'src', 'backend.ts'), 'utf8')
    .matchAll(/\bcallable\b[^(]*\(\s*['"]([A-Za-z_]\w*)['"]\)/g)].map(m => m[1]);
const backendMethods = new Set(
    [...readFileSync(join(root, 'main.py'), 'utf8').matchAll(/^ {4}async def ([A-Za-z_]\w*)\(/gm)].map(m => m[1]),
);

describe('frontend -> backend calls', () => {
    it('finds the calls', () => {
        expect(frontendCalls.length).toBeGreaterThan(20);  // the pattern still finds them
        expect(frontendCalls).toContain('native_overlay_update');
    });

    it.each(frontendCalls.sort())('%s exists in main.py', name => {
        expect(backendMethods).toContain(name);
    });
});
