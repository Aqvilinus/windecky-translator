// vitest globalSetup: build dist/index.js from the current sources before the integration tests load it, so they
// never test a stale bundle. SKIP_PLUGIN_BUILD=1 uses the dist/ that is there (CI builds it once for all steps).
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { rollup, type RollupOptions, type OutputOptions } from 'rollup';

export const BUNDLE = join(__dirname, '..', '..', 'dist', 'index.js');

export default async function setup() {
    if (process.env.SKIP_PLUGIN_BUILD === '1') {
        if (!existsSync(BUNDLE)) throw new Error(`SKIP_PLUGIN_BUILD=1 but ${BUNDLE} does not exist (pnpm build)`);
        return;
    }
    const config: RollupOptions = (await import('../../rollup.config.js')).default;
    const bundle = await rollup({ ...config, onwarn: () => { /* pnpm build shows them */ } });
    try {
        for (const out of [config.output].flat() as OutputOptions[]) await bundle.write(out);
    } finally {
        await bundle.close();
    }
}
