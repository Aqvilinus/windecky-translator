import { defineConfig } from 'vitest/config';

// tests/frontend: unit tests of single modules (node). tests/integration: the built plugin (dist/index.js) in an
// emulated Steam + Decky Loader (happy-dom); buildPlugin.ts builds it first. tests/README.md has the overview.
export default defineConfig({
    test: {
        include: ['tests/frontend/**/*.test.ts', 'tests/integration/**/*.test.ts'],
        environment: 'node',
        globalSetup: ['tests/integration/buildPlugin.ts'],
        testTimeout: 20000,  // the integration tests wait for the plugin's own timers (their waits fail first)
    },
});
