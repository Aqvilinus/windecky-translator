// src/tabs/TabTranslation.tsx - Language and provider settings (its parts are in ./translation/)

import { PanelSection, PanelSectionRow, Dropdown, DropdownItem, SliderField, ToggleField, ButtonItem, DialogButton, Field, Focusable } from "@decky/ui";
import { showModal } from "../modal";
import { VFC, useState, useEffect, useRef, useCallback } from "react";
import { backend } from "../backend";
import { useSettings } from "../SettingsContext";
import { LLM_DEFAULT_MODELS, LLM_KEY_SETTING, LLM_MODEL_SETTING, llmConfigured, llmModel } from "../llm";
import { HiKey, HiLockClosed, HiInformationCircle } from "react-icons/hi2";
import { BsStars, BsWindows } from "react-icons/bs";
import ocrspaceLogo from "../../assets/ocrspace-logo.png";
import googlecloudLogo from "../../assets/googlecloud-logo.png";
import googletranslateLogo from "../../assets/googletranslate-logo.png";
import geminiLogo from "../../assets/gemini-logo.png";
import steamdeckLogo from "../../assets/steamdeck-logo.png";
import chromeLogo from "../../assets/chrome-logo.png";
import { languageOptions, selectLanguageOption, languageLabel, outputLanguageOptions } from "./translation/languages";
import { ApiKeyModal, CustomServerModal } from "./translation/dialogs";
import { CacheEntriesModal } from "./translation/cache";
import { llmBackendOptions, modelOption, ModelPicker, knownGeminiModels } from "./translation/models";
import { useChromeScreenAIStatus, useNllbModelStatus, ModelActionButton, ModelStatusIndicator, ModelHeadingProgressBar, ModelDownloadError, ProviderRating } from "./translation/downloads";

interface TabTranslationProps {
    scrollTarget?: string | null;
    onScrolled?: () => void;
}

export const TabTranslation: VFC<TabTranslationProps> = ({ scrollTarget, onScrolled }) => {
    const { settings, updateSetting } = useSettings();
    const chromescreenaiActionRef = useRef<HTMLDivElement>(null);
    const ct2ActionRef = useRef<HTMLDivElement>(null);
    const csai = useChromeScreenAIStatus();
    const nllb = useNllbModelStatus();
    const [cacheEntries, setCacheEntries] = useState<number | null>(null);
    const [windowsOcrLanguages, setWindowsOcrLanguages] = useState<string[] | null>(null);

    useEffect(() => {
        if (settings.ocrProvider !== 'windows_ocr') return;
        backend.getWindowsOcrLanguages().then(setWindowsOcrLanguages).catch(() => setWindowsOcrLanguages([]));
    }, [settings.ocrProvider]);

    const refreshCacheStats = useCallback(async () => {
        try {
            const stats = await backend.getTranslationCacheStats();
            setCacheEntries(stats?.entries ?? 0);
        } catch {
            setCacheEntries(null);
        }
    }, []);

    useEffect(() => {
        if (settings.translationCacheEnabled) refreshCacheStats();
    }, [settings.translationCacheEnabled, refreshCacheStats]);

    useEffect(() => {
        if (!scrollTarget) return;
        const ref = scrollTarget === 'chromescreenai-action' ? chromescreenaiActionRef
                  : scrollTarget === 'ct2-action' ? ct2ActionRef
                  : null;

        // Wait for Steam's tab transition + focus router to settle before scrolling, otherwise our scroll gets overridden.
        const timeoutId = setTimeout(() => {
            const el = ref?.current as HTMLElement | null;
            if (el) {
                el.focus({ preventScroll: true });
                el.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
            onScrolled?.();
        }, 400);

        return () => clearTimeout(timeoutId);
    }, [scrollTarget]);

    const isCT2 = settings.translationProvider === 'ct2';
    const filteredLanguageOptions = isCT2
        ? languageOptions.filter(lang => lang.data !== "auto")
        : languageOptions;

    const placeholderOption = settings.inputLanguage === '' ? [selectLanguageOption] : [];
    const inputLanguageOptions = [...placeholderOption, ...filteredLanguageOptions];

    // When switching to CT2, if source is auto-detect, clear it so user picks a specific language
    useEffect(() => {
        if (settings.initialized && isCT2 && settings.inputLanguage === 'auto') {
            updateSetting('inputLanguage', '', 'Input language');
        }
    }, [settings.initialized, settings.translationProvider]);

    return (
        <div style={{ paddingBottom: "40px" }}>
            <PanelSection title="Languages">
                <PanelSectionRow>
                    <DropdownItem
                        layout="below"
                        label="Input Language"
                        description={isCT2
                            ? "Source language (auto-detect not available for offline translation)"
                            : "Source language (Select auto-detect if unsure)"}
                        rgOptions={inputLanguageOptions}
                        selectedOption={settings.inputLanguage}
                        onChange={(option: any) => updateSetting('inputLanguage', option.data, 'Input language')}
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
                {/* OCR Provider Selection */}
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
                                    { label: <span style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "8px", width: "100%", height: "20px", lineHeight: "20px" }}><span style={{ display: "flex", alignItems: "center" }}><span>On-Device</span><span style={{ fontSize: "10px", opacity: 0.7, marginLeft: "4px", transform: "translateY(2px)" }}>(Chrome)</span></span><span className="dt-recommended-tag" style={{ fontSize: "10px", color: "#9aa0a6", fontStyle: "italic" }}>★ recommended</span></span>, data: "chromescreenai" },
                                    { label: <span>OCR.space</span>, data: "ocrspace" },
                                    { label: <span style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "8px", width: "100%", height: "20px", lineHeight: "20px" }}><span>Google Cloud</span><span className="dt-recommended-tag" style={{ fontSize: "10px", color: "#9aa0a6", fontStyle: "italic" }}>★ recommended</span></span>, data: "googlecloud" },
                                    { label: <span style={{ display: "flex", alignItems: "center", gap: "6px", height: "20px", lineHeight: "20px" }}>Gemini Vision <BsStars style={{ fontSize: "12px" }} /></span>, data: "gemini_vision" }
                                ]}
                                selectedOption={settings.ocrProvider}
                                onChange={(option) => updateSetting('ocrProvider', option.data, 'OCR provider')}
                            />
                            </div>
                            {settings.ocrProvider === 'googlecloud' && (
                                <DialogButton
                                    onClick={() => {
                                        showModal(
                                            <ApiKeyModal
                                                currentKey={settings.googleApiKey}
                                                onSave={(key) => updateSetting('googleApiKey', key, 'Google API Key')}
                                                title="Google Cloud API Key"
                                                description="Enter your Google Cloud API key for Vision and Translation services."
                                            />
                                        );
                                    }}
                                    style={{ minWidth: "40px", width: "40px", padding: "10px 0" }}
                                >
                                    <div style={{ position: "relative", display: "inline-flex" }}>
                                        <HiKey />
                                        <div style={{
                                            position: "absolute",
                                            bottom: "-8px",
                                            right: "-6px",
                                            width: "6px",
                                            height: "6px",
                                            borderRadius: "50%",
                                            backgroundColor: settings.googleApiKey ? "#4caf50" : "#ff6b6b"
                                        }} />
                                    </div>
                                </DialogButton>
                            )}
                            {settings.ocrProvider === 'gemini_vision' && (
                                <DialogButton
                                    onClick={() => {
                                        showModal(
                                            <ApiKeyModal
                                                currentKey={settings.geminiApiKey}
                                                onSave={(key) => updateSetting('geminiApiKey', key, 'Gemini API Key')}
                                                title="Gemini API Key"
                                                description="Enter your free Gemini API key from aistudio.google.com."
                                            />
                                        );
                                    }}
                                    style={{ minWidth: "40px", width: "40px", padding: "10px 0" }}
                                >
                                    <div style={{ position: "relative", display: "inline-flex" }}>
                                        <HiKey />
                                        <div style={{
                                            position: "absolute",
                                            bottom: "-8px",
                                            right: "-6px",
                                            width: "6px",
                                            height: "6px",
                                            borderRadius: "50%",
                                            backgroundColor: settings.geminiApiKey ? "#4caf50" : "#ff6b6b"
                                        }} />
                                    </div>
                                </DialogButton>
                            )}
                            {settings.ocrProvider === 'chromescreenai' && (
                                <ModelActionButton state={csai} actionRef={chromescreenaiActionRef} />
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
                            {settings.ocrProvider === 'chromescreenai' && (
                                <>
                                    <div style={{ display: "inline-flex", flexDirection: "column" }}>
                                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                                            <img src={chromeLogo} alt="" style={{ height: "18px" }} />
                                            <span style={{ fontWeight: "bold", color: "#dcdedf" }}>On-Device (Chrome Screen AI)</span>
                                        </div>
                                        <ModelHeadingProgressBar state={csai} />
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
                                    {windowsOcrLanguages && settings.inputLanguage && settings.inputLanguage !== 'auto'
                                        && !windowsOcrLanguages.includes(settings.inputLanguage) && (
                                        <div style={{ color: "#ffa726", marginTop: "6px" }}>
                                            No pack for {languageLabel(settings.inputLanguage)}: add the language in Windows Settings &gt;
                                            Time &amp; language &gt; Language &amp; region, or use On-Device (Chrome), which reads 70+
                                            languages without packs
                                        </div>
                                    )}
                                </>
                            )}
                            {settings.ocrProvider === 'ocrspace' && (
                                <>
                                    <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px" }}>
                                        <img src={ocrspaceLogo} alt="" style={{ height: "18px" }} />
                                        <span style={{ fontWeight: "bold", color: "#dcdedf" }}>OCR.space</span>
                                    </div>
                                    <ProviderRating quality={2} speed={3} />
                                    <div>- Free EU-based cloud OCR API</div>
                                    <div>- Max usage limits: 500/day and 10/10min</div>
                                </>
                            )}
                            {settings.ocrProvider === 'googlecloud' && (
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

                {settings.ocrProvider === 'chromescreenai' && (
                    <PanelSectionRow>
                        <ToggleField
                            label="Faster Recognition"
                            description="Keeps the recognition engine loaded in memory between translations"
                            checked={settings.chromeScreenAiPersistentMode}
                            onChange={(value) => {
                                updateSetting('chromeScreenAiPersistentMode', value, 'Faster recognition');
                            }}
                        />
                    </PanelSectionRow>
                )}

                {settings.ocrProvider === 'googlecloud' && (
                    <PanelSectionRow>
                        <ToggleField
                            label="Customize Recognition"
                            description="Fine-tune text recognition parameters. Can make things better or worse"
                            checked={settings.customRecognitionSettings}
                            onChange={(value) => {
                                updateSetting('customRecognitionSettings', value, 'Custom recognition settings');
                                if (!value) {
                                    updateSetting('confidenceThreshold', 0.6, 'Text recognition confidence');
                                }
                            }}
                        />
                    </PanelSectionRow>
                )}

                {settings.customRecognitionSettings && settings.ocrProvider === 'googlecloud' && (
                    <PanelSectionRow>
                        <SliderField
                            value={settings.confidenceThreshold}
                            max={1.0}
                            min={0.0}
                            step={0.05}
                            label="Text Recognition Confidence"
                            description="Minimum confidence level for detected text (higher = fewer false positives)"
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
                                        { label: <span>On-Device</span>, data: "ct2" },
                                        { label: <span>Google Translate</span>, data: "freegoogle" },
                                        { label: <span>Google Cloud</span>, data: "googlecloud" },
                                        { label: <span style={{ display: "flex", alignItems: "center", gap: "6px", height: "20px", lineHeight: "20px" }}>AI Translation <BsStars style={{ fontSize: "12px" }} /></span>, data: "llm" }
                                    ]}
                                    selectedOption={settings.translationProvider}
                                    onChange={(option) => updateSetting('translationProvider', option.data, 'Translation provider')}
                                />
                            </div>
                            {settings.translationProvider === 'llm' && (
                                <DialogButton
                                    onClick={() => {
                                        if (settings.llmBackend === 'custom') {
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
                                        const isGemini = settings.llmBackend === 'gemini';
                                        const keySetting = LLM_KEY_SETTING[settings.llmBackend];
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
                                    }}
                                    style={{ minWidth: "40px", width: "40px", padding: "10px 0" }}
                                >
                                    <div style={{ position: "relative", display: "inline-flex" }}>
                                        <HiKey />
                                        <div style={{
                                            position: "absolute",
                                            bottom: "-8px",
                                            right: "-6px",
                                            width: "6px",
                                            height: "6px",
                                            borderRadius: "50%",
                                            backgroundColor: llmConfigured(settings) ? "#4caf50" : "#ff6b6b"
                                        }} />
                                    </div>
                                </DialogButton>
                            )}
                            {settings.translationProvider === 'googlecloud' && (
                                <DialogButton
                                    onClick={() => {
                                        showModal(
                                            <ApiKeyModal
                                                currentKey={settings.googleApiKey}
                                                onSave={(key) => updateSetting('googleApiKey', key, 'Google API Key')}
                                                title="Google Cloud API Key"
                                                description="Enter your Google Cloud API key for Translation services."
                                            />
                                        );
                                    }}
                                    style={{ minWidth: "40px", width: "40px", padding: "10px 0" }}
                                >
                                    <div style={{ position: "relative", display: "inline-flex" }}>
                                        <HiKey />
                                        <div style={{
                                            position: "absolute",
                                            bottom: "-8px",
                                            right: "-6px",
                                            width: "6px",
                                            height: "6px",
                                            borderRadius: "50%",
                                            backgroundColor: settings.googleApiKey ? "#4caf50" : "#ff6b6b"
                                        }} />
                                    </div>
                                </DialogButton>
                            )}
                            {settings.translationProvider === 'ct2' && (
                                <ModelActionButton state={nllb} actionRef={ct2ActionRef} />
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
                                rgOptions={llmBackendOptions}
                                selectedOption={settings.llmBackend}
                                onChange={(option) => updateSetting('llmBackend', option.data, 'AI service')}
                            />
                        </PanelSectionRow>
                        <ModelPicker
                            label="AI Model"
                            source={settings.llmBackend}
                            listModels={(llm) => backend.getLlmModels(llm)}
                            fallback={(LLM_DEFAULT_MODELS[settings.llmBackend] || []).map(modelOption)}
                            placeholder="Select model..."
                            selectedModel={llmModel(settings)}
                            canList={llmConfigured(settings) || (settings.llmBackend === 'custom' && !!settings.llmCustomUrl)}
                            onChange={(model) => updateSetting(LLM_MODEL_SETTING[settings.llmBackend], model, 'AI model')}
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
                                        {settings.llmBackend === 'gemini'
                                            ? <img src={geminiLogo} alt="" style={{ height: "18px" }} />
                                            : <BsStars style={{ fontSize: "16px", color: "#dcdedf" }} />}
                                        <span style={{ fontWeight: "bold", color: "#dcdedf" }}>
                                            AI Translation ({settings.llmBackend === 'gemini' ? 'Gemini' : settings.llmBackend === 'groq' ? 'Groq' : 'Custom server'})
                                        </span>
                                    </div>
                                    <ProviderRating quality={3} speed={settings.llmBackend === 'groq' ? 3 : 2} />
                                    <div>- Translates the whole screen at once, with context</div>
                                    <div>- Google Translate, then Bing, take over when the AI is unavailable or rate-limited</div>
                                    {settings.llmBackend === 'gemini' && (
                                        <>
                                            <div>- Free API key at aistudio.google.com</div>
                                            <div>- EU/EEA, UK, Switzerland: Google's terms require billing on the key's project</div>
                                        </>
                                    )}
                                    {settings.llmBackend === 'groq' && <div>- Free API key at console.groq.com, about 1,000 requests a day</div>}
                                    {settings.llmBackend === 'custom' && <div>- Any OpenAI-compatible API: OpenRouter, a local llama.cpp server...</div>}
                                    {!llmConfigured(settings) && (
                                        <div style={{ color: "#ff6b6b", marginTop: "4px" }}>
                                            {settings.llmBackend === 'custom'
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
                            {settings.ocrProvider !== 'gemini_vision' && settings.translationProvider === 'freegoogle' && (
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
                            {settings.ocrProvider !== 'gemini_vision' && settings.translationProvider === 'googlecloud' && (
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
                            {settings.ocrProvider !== 'gemini_vision' && settings.translationProvider === 'ct2' && (
                                <>
                                    <div style={{ display: "inline-flex", flexDirection: "column" }}>
                                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                                            <img src={steamdeckLogo} alt="" style={{ height: "18px" }} />
                                            <span style={{ fontWeight: "bold", color: "#dcdedf" }}>On-Device (NLLB-200 1.3B)</span>
                                        </div>
                                        <ModelHeadingProgressBar state={nllb} />
                                    </div>
                                    <ModelStatusIndicator state={nllb} />
                                    <ModelDownloadError state={nllb} />
                                    <ProviderRating quality={1} speed={1} />
                                    <div>- Offline and privacy-friendly translation</div>
                                    <div>- Requires 1.4GB one-time model download</div>
                                    <div>- Single model covers most languages</div>
                                    <div>- Language auto-detect not supported</div>
                                    <div>- Experimental support</div>
                                    {(settings.inputLanguage === 'auto' || settings.inputLanguage === '') && (
                                        <div style={{ color: "#ffa726", marginTop: "6px" }}>
                                            Offline translation needs a specific source language. Select one in the Languages section above.
                                        </div>
                                    )}
                                </>
                            )}
                        </div>
                    </Field>
                </PanelSectionRow>

                {settings.translationProvider === 'ct2' && (
                    <PanelSectionRow>
                        <ToggleField
                            label="Faster Translation"
                            description="Keeps the translation model loaded in memory between translations"
                            checked={settings.ct2PersistentMode}
                            onChange={(value) => {
                                updateSetting('ct2PersistentMode', value, 'Faster translation');
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
