// Which platform the frontend runs on. A module of its own, so Input.tsx can use it without importing windows.ts
// (which imports Input.tsx).
export const IS_WINDOWS = typeof navigator !== 'undefined' && /Windows/.test(navigator.userAgent);
