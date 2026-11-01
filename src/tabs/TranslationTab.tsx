import { PanelSection, PanelSectionRow, Dropdown, DropdownItem, SliderField, ToggleField, ButtonItem, Field, Focusable } from "@decky/ui";
import { showModal } from "../steam";
import { VFC, useState, useEffect, useRef, useCallback } from "react";
import { backend } from "../backend";
import { useSettings } from "../settings";
import { CONFIDENCE_OCR_PROVIDERS, LLM_DEFAULT_MODELS, LLM_KEY_SETTING, LLM_MODEL_SETTING, llmConfigured, llmModel } from "../providers";
import { HiLockClosed, HiInformationCircle } from "react-icons/hi2";
import { BsStars, BsWindows } from "react-icons/bs";
import googlecloudLogo from "../../assets/googlecloud-logo.png";
import googletranslateLogo from "../../assets/googletranslate-logo.png";
import geminiLogo from "../../assets/gemini-logo.png";
import steamdeckLogo from "../../assets/steamdeck-logo.png";
import chromeLogo from "../../assets/chrome-logo.png";
import { languageOptions, selectLanguageOption, languageLabel, outputLanguageOptions } from "./translation/languages";
import { ApiKeyModal, CustomServerModal, KeyButton } from "./translation/dialogs";
import { CacheEntriesModal } from "./translation/cache";
import { llmServiceOptions, modelOption, ModelPicker, knownGeminiModels } from "./translation/models";
import { useModelDownload, ModelActionButton, ModelStatusIndicator, ModelProgressBar, ModelDownloadError, ProviderRating } from "./translation/downloads";

// a scroll before Steam's tab transition and focus router settle gets overridden
const TAB_TRANSITION_SETTLE_MS = 400;

interface TranslationTabProps {
    scrollTarget?: string | null;
    onScrolled?: () => void;
}

export const TranslationTab: VFC<TranslationTabProps> = ({ scrollTarget, onScrolled }) => {
    const { settings, updateSetting } = useSettings();
    const chromeScreenAiActionRef = useRef<HTMLDivElement>(null);
    const nllbActionRef = useRef<HTMLDivElement>(null);
    const csai = useModelDownload('chrome_screen_ai', 80);  // sizes until the backend answers
    const nllb = useModelDownload('nllb', 1410);
    const [cacheEntries, setCacheEntries] = useState<number | null>(null);
    const [windowsOcrLanguages, setWindowsOcrLanguages] = useState<string[] | null>(null);

    useEffect(() => {
        if (settings.ocrProvider !== 'windows_ocr') return;
        backend.getWindowsOcrLanguages().then(setWindowsOcrLanguages).catch(() => setWindowsOcrLanguages([]));
    }, [settings.ocrProvider]);

    const refreshCacheStats = useCallback(async () => {
        try {
            setCacheEntries(await backend.countTranslationCacheEntries());
        } catch {
            setCacheEntries(null);
        }
    }, []);

    useEffect(() => {
        if (settings.translationCacheEnabled) refreshCacheStats();
    }, [settings.translationCacheEnabled, refreshCacheStats]);

    useEffect(() => {
        if (!scrollTarget) return;
        const ref = scrollTarget === 'chrome_screen_ai-action' ? chromeScreenAiActionRef
                  : scrollTarget === 'nllb-action' ? nllbActionRef
                  : null;

        const timeoutId = setTimeout(() => {
            const el = ref?.current as HTMLElement | null;
            if (el) {
                el.focus({ preventScroll: true });
                el.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
            onScrolled?.();
        }, TAB_TRANSITION_SETTLE_MS);

        return () => clearTimeout(timeoutId);
    }, [scrollTarget]);

    const isNllb = settings.translationProvider === 'nllb';
    const filteredLanguageOptions = isNllb
        ? languageOptions.filter(lang => lang.data !== "auto")
        : languageOptions;

    const placeholderOption = settings.sourceLanguage === '' ? [selectLanguageOption] : [];
    const sourceLanguageOptions = [...placeholderOption, ...filteredLanguageOptions];

    // NLLB can't detect the source language: the user picks one
    useEffect(() => {
        if (isNllb && settings.sourceLanguage === 'auto') {
            updateSetting('sourceLanguage', '', 'Input language');
        }
    }, [settings.translationProvider]);

    return (
        <div style={{ paddingBottom: "40px" }}>
            <PanelSection title="Languages">
                <PanelSectionRow>
                    <DropdownItem
                        layout="below"
                        label="Input Language"
                        description={isNllb
                            ? "Source language (auto-detect not available for offline translation)"
                            : "Source language (Select auto-detect if unsure)"}
                        rgOptions={sourceLanguageOptions}
                        selectedOption={settings.sourceLanguage}
                        onChange={(option: any) => updateSetting('sourceLanguage', option.data, 'Input language')}
                    />
                </PanelSectionRow>

                <PanelSectionRow>
                    <DropdownItem
                        layout="below"
                        label="Output Language"
                        description="Target language for translation"
                        rgOptions={[...(settings.targetLanguage === '' ? [selectLanguageOption] : []), ...outputLanguageOptions]}
                        selectedOption={settings.targetLanguage}
                        onChange={(option: any) => updateSetting('targetLanguage', option.data, 'Output language')}
                    />
                </PanelSectionRow>
            </PanelSection>

            <PanelSection title="Recognition">
                <PanelSectionRow>
                    <Field
                        label="Text Recognition Method"
                        childrenContainerWidth="max"
                        childrenLayout="below"
                        focusable={false}
                    >
                        <Focusable style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                            <div className="dt-ocr-dropdown-wrapper" style={{ flex: 1 }}>
                                <style>{`.dt-ocr-dropdown-wrapper .dt-recommended-tag { display: none !important; }`}</style>
                            <Dropdown
                                rgOptions={[
                                    { label: <span style={{ display: "flex", alignItems: "center", height: "20px", lineHeight: "20px" }}><span>On-Device</span><span style={{ fontSize: "10px", opacity: 0.7, marginLeft: "4px", transform: "translateY(2px)" }}>(Windows OCR)</span></span>, data: "windows_ocr" },
                                    { label: <span style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "8px", width: "100%", height: "20px", lineHeight: "20px" }}><span style={{ display: "flex", alignItems: "center" }}><span>On-Device</span><span style={{ fontSize: "10px", opacity: 0.7, marginLeft: "4px", transform: "translateY(2px)" }}>(Chrome)</span></span><span className="dt-recommended-tag" style={{ fontSize: "10px", color: "#9aa0a6", fontStyle: "italic" }}>★ recommended</span></span>, data: "chrome_screen_ai" },
                                    { label: <span style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "8px", width: "100%", height: "20px", lineHeight: "20px" }}><span>Google Cloud</span><span className="dt-recommended-tag" style={{ fontSize: "10px", color: "#9aa0a6", fontStyle: "italic" }}>★ recommended</span></span>, data: "google_cloud" },
                                    { label: <span style={{ display: "flex", alignItems: "center", gap: "6px", height: "20px", lineHeight: "20px" }}>Gemini Vision <BsStars style={{ fontSize: "12px" }} /></span>, data: "gemini_vision" }
                                ]}
                                selectedOption={settings.ocrProvider}
                                onChange={(option) => updateSetting('ocrProvider', option.data, 'OCR provider')}
                            />
                            </div>
                            {settings.ocrProvider === 'google_cloud' && (
                                <KeyButton hasKey={!!settings.googleApiKey} onClick={() => {
                                    showModal(
                                        <ApiKeyModal
                                            currentKey={settings.googleApiKey}
                                            onSave={(key) => updateSetting('googleApiKey', key, 'Google API Key')}
                                            title="Google Cloud API Key"
                                            description="Enter your Google Cloud API key for Vision and Translation services."
                                        />
                                    );
                                }} />
                            )}
                            {settings.ocrProvider === 'gemini_vision' && (
                                <KeyButton hasKey={!!settings.geminiApiKey} onClick={() => {
                                    showModal(
                                        <ApiKeyModal
                                            currentKey={settings.geminiApiKey}
                                            onSave={(key) => updateSetting('geminiApiKey', key, 'Gemini API Key')}
                                            title="Gemini API Key"
                                            description="Enter your free Gemini API key from aistudio.google.com."
                                        />
                                    );
                                }} />
                            )}
                            {settings.ocrProvider === 'chrome_screen_ai' && (
                                <ModelActionButton state={csai} actionRef={chromeScreenAiActionRef} />
                            )}
                        </Focusable>
                    </Field>
                </PanelSectionRow>
                {settings.ocrProvider === 'gemini_vision' && (
                    <ModelPicker
                        label="Gemini Model"
                        listModels={() => backend.getGeminiModels()}
                        fallback={knownGeminiModels}
                        knownOnly={true}
                        canList={!!settings.geminiApiKey}
                        selectedModel={settings.geminiModel}
                        onChange={(model) => updateSetting('geminiModel', model, 'Gemini model')}
                    />
                )}
                <PanelSectionRow>
                    <Field
                        focusable={true}
                        childrenContainerWidth="max"
                        childrenLayout="below"
                    >
                        <div style={{ color: "#8b929a", fontSize: "12px", lineHeight: "1.6", paddingLeft: "4px", paddingTop: "4px" }}>
                            {settings.ocrProvider === 'chrome_screen_ai' && (
                                <>
                                    <div style={{ display: "inline-flex", flexDirection: "column" }}>
                                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                                            <img src={chromeLogo} alt="" style={{ height: "18px" }} />
                                            <span style={{ fontWeight: "bold", color: "#dcdedf" }}>On-Device (Chrome Screen AI)</span>
                                        </div>
                                        <ModelProgressBar state={csai} />
                                    </div>
                                    <ModelStatusIndicator state={csai} />
                                    <ModelDownloadError state={csai} />
                                    <ProviderRating quality={3} speed={2} />
                                    <div>- Offline and privacy-friendly text recognition</div>
                                    <div>- Requires 80MB one-time engine download</div>
                                    <div>- Auto-detects 70+ languages</div>
                                    <div style={{ marginTop: "6px", fontStyle: "italic", color: "#5f6268", fontSize: "10px" }}>
                                        Downloaded on demand from Google's public server
                                    </div>
                                    <div style={{ fontStyle: "italic", color: "#5f6268", fontSize: "10px" }}>
                                        This plugin is not affiliated with or endorsed by Google
                                    </div>
                                </>
                            )}
                            {settings.ocrProvider === 'windows_ocr' && (
                                <>
                                    <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px" }}>
                                        <BsWindows style={{ fontSize: "16px", color: "#dcdedf" }} />
                                        <span style={{ fontWeight: "bold", color: "#dcdedf" }}>On-Device (Windows OCR)</span>
                                    </div>
                                    <ProviderRating quality={2} speed={3} />
                                    <div>- Built into Windows, no download</div>
                                    <div>- Each language needs its Windows language pack with text recognition</div>
                                    <div>- Installed: {windowsOcrLanguages === null ? '...' :
                                        windowsOcrLanguages.length ? windowsOcrLanguages.map(languageLabel).join(', ') : 'none'}</div>
                                    {windowsOcrLanguages && settings.sourceLanguage && settings.sourceLanguage !== 'auto'
                                        && !windowsOcrLanguages.includes(settings.sourceLanguage) && (
                                        <div style={{ color: "#ffa726", marginTop: "6px" }}>
                                            No pack for {languageLabel(settings.sourceLanguage)}: add the language in Windows Settings &gt;
                                            Time &amp; language &gt; Language &amp; region, or use On-Device (Chrome), which reads 70+
                                            languages without packs
                                        </div>
                                    )}
                                </>
                            )}
                            {settings.ocrProvider === 'google_cloud' && (
                                <>
                                    <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px" }}>
                                        <img src={googlecloudLogo} alt="" style={{ height: "18px" }} />
                                        <span style={{ fontWeight: "bold", color: "#dcdedf" }}>Google Cloud Vision</span>
                                    </div>
                                    <ProviderRating quality={3} speed={3} />
                                    <div>- Best accuracy and speed available</div>
                                    <div>- Ideal for complex/stylized text</div>
                                    <div>- Requires API key</div>
                                    {!settings.googleApiKey && (
                                        <div style={{ color: "#ff6b6b", marginTop: "4px" }}>You need to add your API Key</div>
                                    )}
                                </>
                            )}
                            {settings.ocrProvider === 'gemini_vision' && (
                                <>
                                    <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px" }}>
                                        <img src={geminiLogo} alt="" style={{ height: "18px" }} />
                                        <span style={{ fontWeight: "bold", color: "#dcdedf" }}>Gemini Vision</span>
                                    </div>
                                    <ProviderRating quality={3} speed={1} />
                                    <div>- AI-based Recognition and Translation</div>
                                    <div>- Great accuracy, context-aware translations</div>
                                    <div>- Free API key available at aistudio.google.com</div>
                                    {!settings.geminiApiKey && (
                                        <div style={{ color: "#ff6b6b", marginTop: "4px" }}>You need to add your Gemini API Key</div>
                                    )}
                                </>
                            )}
                        </div>
                    </Field>
                </PanelSectionRow>

                {settings.ocrProvider === 'chrome_screen_ai' && (
                    <PanelSectionRow>
                        <ToggleField
                            label="Faster Recognition"
                            description="Keeps the recognition engine loaded in memory between translations"
                            checked={settings.chromeScreenAiKeepAlive}
                            onChange={(value) => {
                                updateSetting('chromeScreenAiKeepAlive', value, 'Faster recognition');
                            }}
                        />
                    </PanelSectionRow>
                )}

                {CONFIDENCE_OCR_PROVIDERS.has(settings.ocrProvider) && (
                    <PanelSectionRow>
                        <SliderField
                            value={settings.confidenceThreshold}
                            max={1.0}
                            min={0.0}
                            step={0.05}
                            label="Text Recognition Confidence"
                            description="Lines the engine is less sure of are skipped: higher = fewer false finds, lower = more faint text"
                            showValue={true}
                            valueSuffix=""
                            onChange={(value) => {
                                updateSetting('confidenceThreshold', value, 'Text recognition confidence');
                            }}
                        />
                    </PanelSectionRow>
                )}

            </PanelSection>

            <PanelSection title="Translation">
                <PanelSectionRow>
                    <Field
                        label="Text Translation Method"
                        childrenContainerWidth="max"
                        childrenLayout="below"
                        focusable={false}
                    >
                        {settings.ocrProvider === 'gemini_vision' ? (
                            <Dropdown
                                rgOptions={[
                                    { label: <span style={{ display: "flex", alignItems: "center", gap: "6px", height: "20px", lineHeight: "20px" }}><HiLockClosed style={{ fontSize: "12px", color: "#888" }} /> Gemini Vision <BsStars style={{ fontSize: "12px" }} /></span>, data: "gemini_vision" }
                                ]}
                                selectedOption="gemini_vision"
                                disabled={true}
                                onChange={() => {}}
                            />
                        ) : (
                        <Focusable style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                            <div style={{ flex: 1 }}>
                                <Dropdown
                                    rgOptions={[
                                        { label: <span>On-Device</span>, data: "nllb" },
                                        { label: <span>Google Translate</span>, data: "google_web" },
                                        { label: <span>Google Cloud</span>, data: "google_cloud" },
                                        { label: <span style={{ display: "flex", alignItems: "center", gap: "6px", height: "20px", lineHeight: "20px" }}>AI Translation <BsStars style={{ fontSize: "12px" }} /></span>, data: "llm" }
                                    ]}
                                    selectedOption={settings.translationProvider}
                                    onChange={(option) => updateSetting('translationProvider', option.data, 'Translation provider')}
                                />
                            </div>
                            {settings.translationProvider === 'llm' && (
                                <KeyButton hasKey={llmConfigured(settings)} onClick={() => {
                                    if (settings.llmService === 'custom') {
                                        showModal(
                                            <CustomServerModal
                                                url={settings.llmCustomUrl}
                                                apiKey={settings.llmCustomApiKey}
                                                model={settings.llmCustomModel}
                                                onSave={(url, key, model) => {
                                                    updateSetting('llmCustomUrl', url, 'AI server address');
                                                    updateSetting('llmCustomApiKey', key, 'AI server key');
                                                    updateSetting('llmCustomModel', model, 'AI model');
                                                }}
                                            />
                                        );
                                        return;
                                    }
                                    const isGemini = settings.llmService === 'gemini';
                                    const keySetting = LLM_KEY_SETTING[settings.llmService];
                                    showModal(
                                        <ApiKeyModal
                                            currentKey={String(settings[keySetting] || '')}
                                            onSave={(key) => updateSetting(keySetting, key, isGemini ? 'Gemini API Key' : 'Groq API Key')}
                                            title={isGemini ? "Gemini API Key" : "Groq API Key"}
                                            description={isGemini
                                                ? "Free key at aistudio.google.com. In the EU/EEA, UK and Switzerland Google's terms allow only paid use: enable billing on the key's project (game text costs cents a month). Also used by Gemini Vision."
                                                : "Free key at console.groq.com (no card needed)."}
                                        />
                                    );
                                }} />
                            )}
                            {settings.translationProvider === 'google_cloud' && (
                                <KeyButton hasKey={!!settings.googleApiKey} onClick={() => {
                                    showModal(
                                        <ApiKeyModal
                                            currentKey={settings.googleApiKey}
                                            onSave={(key) => updateSetting('googleApiKey', key, 'Google API Key')}
                                            title="Google Cloud API Key"
                                            description="Enter your Google Cloud API key for Translation services."
                                        />
                                    );
                                }} />
                            )}
                            {settings.translationProvider === 'nllb' && (
                                <ModelActionButton state={nllb} actionRef={nllbActionRef} />
                            )}
                        </Focusable>
                        )}
                    </Field>
                </PanelSectionRow>

                {settings.ocrProvider !== 'gemini_vision' && settings.translationProvider === 'llm' && (
                    <>
                        <PanelSectionRow>
                            <DropdownItem
                                layout="below"
                                label="AI Service"
                                rgOptions={llmServiceOptions}
                                selectedOption={settings.llmService}
                                onChange={(option) => updateSetting('llmService', option.data, 'AI service')}
                            />
                        </PanelSectionRow>
                        <ModelPicker
                            label="AI Model"
                            source={settings.llmService}
                            listModels={(llm) => backend.getLlmModels(llm)}
                            fallback={(LLM_DEFAULT_MODELS[settings.llmService] || []).map(modelOption)}
                            placeholder="Select model..."
                            selectedModel={llmModel(settings)}
                            canList={llmConfigured(settings) || (settings.llmService === 'custom' && !!settings.llmCustomUrl)}
                            onChange={(model) => updateSetting(LLM_MODEL_SETTING[settings.llmService], model, 'AI model')}
                        />
                    </>
                )}

                <PanelSectionRow>
                    <Field
                        focusable={true}
                        childrenContainerWidth="max"
                        childrenLayout="below"
                    >
                        <div style={{ color: "#8b929a", fontSize: "12px", lineHeight: "1.6", paddingLeft: "4px", paddingTop: "4px" }}>
                            {settings.ocrProvider !== 'gemini_vision' && settings.translationProvider === 'llm' && (
                                <>
                                    <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px" }}>
                                        {settings.llmService === 'gemini'
                                            ? <img src={geminiLogo} alt="" style={{ height: "18px" }} />
                                            : <BsStars style={{ fontSize: "16px", color: "#dcdedf" }} />}
                                        <span style={{ fontWeight: "bold", color: "#dcdedf" }}>
                                            AI Translation ({settings.llmService === 'gemini' ? 'Gemini' : settings.llmService === 'groq' ? 'Groq' : 'Custom server'})
                                        </span>
                                    </div>
                                    <ProviderRating quality={3} speed={settings.llmService === 'groq' ? 3 : 2} />
                                    <div>- Translates the whole screen at once, with context</div>
                                    <div>- Google Translate, then Bing, take over when the AI is unavailable or rate-limited</div>
                                    {settings.llmService === 'gemini' && (
                                        <>
                                            <div>- Free API key at aistudio.google.com</div>
                                            <div>- EU/EEA, UK, Switzerland: Google's terms require billing on the key's project</div>
                                        </>
                                    )}
                                    {settings.llmService === 'groq' && <div>- Free API key at console.groq.com, about 1,000 requests a day</div>}
                                    {settings.llmService === 'custom' && <div>- Any OpenAI-compatible API: OpenRouter, a local llama.cpp server...</div>}
                                    {!llmConfigured(settings) && (
                                        <div style={{ color: "#ff6b6b", marginTop: "4px" }}>
                                            {settings.llmService === 'custom'
                                                ? "Set the server address and model with the key button (Google Translate is used until then)"
                                                : "You need to add your API Key (Google Translate is used until then)"}
                                        </div>
                                    )}
                                </>
                            )}
                            {settings.ocrProvider === 'gemini_vision' && (
                                <>
                                    <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px" }}>
                                        <img src={geminiLogo} alt="" style={{ height: "18px" }} />
                                        <span style={{ fontWeight: "bold", color: "#dcdedf" }}>Gemini Vision</span>
                                    </div>
                                    <ProviderRating quality={3} speed={1} />
                                    <div>- Translation is handled by Gemini Vision</div>
                                    <div>- OCR and translation happen in a single step</div>
                                </>
                            )}
                            {settings.ocrProvider !== 'gemini_vision' && settings.translationProvider === 'google_web' && (
                                <>
                                    <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px" }}>
                                        <img src={googletranslateLogo} alt="" style={{ height: "18px" }} />
                                        <span style={{ fontWeight: "bold", color: "#dcdedf" }}>Google Translate</span>
                                    </div>
                                    <ProviderRating quality={2} speed={3} />
                                    <div>- Free, no API key needed</div>
                                    <div>- Good quality for most languages</div>
                                </>
                            )}
                            {settings.ocrProvider !== 'gemini_vision' && settings.translationProvider === 'google_cloud' && (
                                <>
                                    <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px" }}>
                                        <img src={googlecloudLogo} alt="" style={{ height: "18px" }} />
                                        <span style={{ fontWeight: "bold", color: "#dcdedf" }}>Google Cloud Translation</span>
                                    </div>
                                    <ProviderRating quality={3} speed={3} />
                                    <div>- High quality translations</div>
                                    <div>- Requires API key</div>
                                    {!settings.googleApiKey && (
                                        <div style={{ color: "#ff6b6b", marginTop: "4px" }}>You need to add your API Key</div>
                                    )}
                                </>
                            )}
                            {settings.ocrProvider !== 'gemini_vision' && settings.translationProvider === 'nllb' && (
                                <>
                                    <div style={{ display: "inline-flex", flexDirection: "column" }}>
                                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                                            <img src={steamdeckLogo} alt="" style={{ height: "18px" }} />
                                            <span style={{ fontWeight: "bold", color: "#dcdedf" }}>On-Device (NLLB-200 1.3B)</span>
                                        </div>
                                        <ModelProgressBar state={nllb} />
                                    </div>
                                    <ModelStatusIndicator state={nllb} />
                                    <ModelDownloadError state={nllb} />
                                    <ProviderRating quality={1} speed={1} />
                                    <div>- Offline and privacy-friendly translation</div>
                                    <div>- Requires 1.4GB one-time model download</div>
                                    <div>- Single model covers most languages</div>
                                    <div>- Language auto-detect not supported</div>
                                    <div>- Experimental support</div>
                                    {(settings.sourceLanguage === 'auto' || settings.sourceLanguage === '') && (
                                        <div style={{ color: "#ffa726", marginTop: "6px" }}>
                                            Offline translation needs a specific source language. Select one in the Languages section above.
                                        </div>
                                    )}
                                </>
                            )}
                        </div>
                    </Field>
                </PanelSectionRow>

                {settings.translationProvider === 'nllb' && (
                    <PanelSectionRow>
                        <ToggleField
                            label="Faster Translation"
                            description="Keeps the translation model loaded in memory between translations"
                            checked={settings.nllbKeepAlive}
                            onChange={(value) => {
                                updateSetting('nllbKeepAlive', value, 'Faster translation');
                            }}
                        />
                    </PanelSectionRow>
                )}

                <PanelSectionRow>
                    <ToggleField
                        label="Cache Translations"
                        description={<>
                            Save translated sentences to avoid translating them again and making the process faster.
                            <div style={{ display: "flex", alignItems: "center", gap: "5px", marginTop: "5px", fontSize: "11px", opacity: 0.6 }}>
                                <HiInformationCircle style={{ fontSize: "13px", flexShrink: 0 }} />
                                <span>A lower-quality engine can reuse results from a higher-quality one, but not the other way around</span>
                            </div>
                        </>}
                        checked={settings.translationCacheEnabled}
                        onChange={(value) => {
                            updateSetting('translationCacheEnabled', value, 'Translation cache');
                            if (value) refreshCacheStats();
                        }}
                    />
                </PanelSectionRow>

                {settings.translationCacheEnabled && (
                    <PanelSectionRow>
                        <ButtonItem
                            layout="below"
                            onClick={() => showModal(<CacheEntriesModal onCleared={refreshCacheStats} />)}
                        >
                            View Cached Translations
                        </ButtonItem>
                    </PanelSectionRow>
                )}

                {settings.translationCacheEnabled && cacheEntries !== null && (
                    <PanelSectionRow>
                        <div style={{ width: "100%", textAlign: "center", fontSize: "12px", color: "#8b929a" }}>{cacheEntries} cached items</div>
                    </PanelSectionRow>
                )}

            </PanelSection>
        </div>
    );
};
