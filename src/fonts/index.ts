// fonts/index.ts - Barrel export for font modules

export { isDyslexiaFont, getDyslexiaFontsForLanguage, loadDyslexiaFont, preloadDyslexiaFonts, cleanupDyslexiaFonts } from "./dyslexiaFonts";
export { WEB_FONTS, LANGUAGE_WEB_FONTS, getWebFontsForLanguage, isWebFont, loadGoogleFont, preloadWebFontList, cleanupWebFonts } from "./webFonts";
export {
    DEFAULT_TRANSLATED_FONT_FAMILY,
    resolveFontStyleCSS,
    quoteFontName,
    LOCAL_FONT_CANDIDATES,
    detectAvailableFonts,
    ensureFontFaceRegistered,
    ensureAllFontFaces,
    buildTranslatedFontFamily,
    ensureFontLoaded,
    useFontOptions,
    isRemoteFont,
    loadRemoteFont,
    cleanupFontFaces,
} from "./fontPresets";
export type { FontStyleOption } from "./fontPresets";

import { cleanupWebFonts } from "./webFonts";
import { cleanupDyslexiaFonts } from "./dyslexiaFonts";
import { cleanupFontFaces } from "./fontPresets";

/** Remove all font-related <style> and <link> elements injected by the plugin. */
export function cleanupAllFontDOM(): void {
    cleanupFontFaces();
    cleanupWebFonts();
    cleanupDyslexiaFonts();
}
