// The language lists of the settings, and a byte-size formatter


// Language options with flag emojis
export const languageOptions = [
    { label: "\ud83c\udf10 Auto-detect", data: "auto" },
    { label: "\ud83c\uddf8\ud83c\udde6 Arabic", data: "ar" },
    { label: "\ud83c\udde7\ud83c\uddec Bulgarian", data: "bg" },
    { label: "\ud83c\udde8\ud83c\uddf3 Chinese (Simplified)", data: "zh-CN" },
    { label: "\ud83c\uddf9\ud83c\uddfc Chinese (Traditional)", data: "zh-TW" },
    { label: "\ud83c\udded\ud83c\uddf7 Croatian", data: "hr" },
    { label: "\ud83c\udde8\ud83c\uddff Czech", data: "cs" },
    { label: "\ud83c\udde9\ud83c\uddf0 Danish", data: "da" },
    { label: "\ud83c\uddf3\ud83c\uddf1 Dutch", data: "nl" },
    { label: "\ud83c\uddec\ud83c\udde7 English", data: "en" },
    { label: "\ud83c\uddeb\ud83c\uddee Finnish", data: "fi" },
    { label: "\ud83c\uddeb\ud83c\uddf7 French", data: "fr" },
    { label: "\ud83c\udde9\ud83c\uddea German", data: "de" },
    { label: "\ud83c\uddec\ud83c\uddf7 Greek", data: "el" },
    { label: "\ud83c\uddee\ud83c\uddf3 Hindi", data: "hi" },
    { label: "\ud83c\udded\ud83c\uddfa Hungarian", data: "hu" },
    { label: "\ud83c\uddee\ud83c\uddf9 Italian", data: "it" },
    { label: "\ud83c\uddef\ud83c\uddf5 Japanese", data: "ja" },
    { label: "\ud83c\uddf0\ud83c\uddf7 Korean", data: "ko" },
    { label: "\ud83c\uddf3\ud83c\uddf4 Norwegian", data: "no" },
    { label: "\ud83c\uddf5\ud83c\uddf1 Polish", data: "pl" },
    { label: "\ud83c\uddf5\ud83c\uddf9 Portuguese", data: "pt" },
    { label: "\ud83c\uddf7\ud83c\uddf4 Romanian", data: "ro" },
    { label: "\ud83c\uddf7\ud83c\uddfa Russian", data: "ru" },
    { label: "\ud83c\uddea\ud83c\uddf8 Spanish", data: "es" },
    { label: "\ud83c\uddf8\ud83c\uddea Swedish", data: "sv" },
    { label: "\ud83c\uddf9\ud83c\udded Thai", data: "th" },
    { label: "\ud83c\uddf9\ud83c\uddf7 Turkish", data: "tr" },
    { label: "\ud83c\uddfa\ud83c\udde6 Ukrainian", data: "uk" },
    { label: "\ud83c\uddfb\ud83c\uddf3 Vietnamese", data: "vi" }
];

export const selectLanguageOption = { label: "Select language...", data: "" };
export const languageLabel = (code: string) => (languageOptions.find(l => l.data === code)?.label || code).replace(/^\S+\s/, "");
export const outputLanguageOptions = languageOptions.filter(lang => lang.data !== "auto");

export function formatBytes(bytes: number): string {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + ' KB';
    return Math.round(bytes / (1024 * 1024)) + ' MB';
}
