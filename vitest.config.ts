import { defineConfig } from 'vitest/config';

// Unit tests for the frontend logic (tests/frontend). Steam's modules (@decky/api, @decky/ui) are mocked per test;
// tests/device holds the checks that need Steam and Decky Loader running.
export default defineConfig({
    test: {
        include: ['tests/frontend/**/*.test.ts'],
        environment: 'node',
    },
});
