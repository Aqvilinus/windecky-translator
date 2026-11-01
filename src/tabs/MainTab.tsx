import {
    ButtonItem,
    PanelSection,
    PanelSectionRow,
    ToggleField
} from "@decky/ui";

import { VFC } from "react";
import { OCR_PROVIDER_LABELS, TRANSLATION_PROVIDER_LABELS } from "../providers";
import { BsTranslate, BsXLg, BsEye, BsStars } from "react-icons/bs";
import { HiInboxArrowDown } from "react-icons/hi2";
import { useSettings } from "../settings";
import type { ModelKind, ModelStatus } from "../backend";
import { Translator } from "../translator";
import { LLM_SERVICE_LABELS, llmModel } from "../providers";
import { logger } from "../log";
import { closeAllSideMenus } from "../steam";

const DOT_OK = '#4caf50', DOT_FAILED = '#ff6b6b', DOT_PENDING = '#888', DOT_INSTALLING = '#ffa726';

const Dot: VFC<{ color: string }> = ({ color }) => (
    <span style={{
        display: 'inline-block', width: '5px', height: '5px', borderRadius: '50%', backgroundColor: color,
        marginRight: '6px', flexShrink: 0
    }} />
);

type ReachResult = { ok: boolean; reason: string; provider: string } | null | undefined;

const ReachabilityRow: VFC<{ result: ReachResult; expectedProvider: string }> = ({ result, expectedProvider }) => {
    if (!result || result.provider !== expectedProvider) {
        return (
            <div style={{ color: '#666', fontSize: '10px', display: 'flex', alignItems: 'center' }}>
                <Dot color={DOT_PENDING} />
                <span>Checking...</span>
            </div>
        );
    }
    return (
        <div style={{ color: '#666', fontSize: '10px', display: 'flex', alignItems: 'center' }}>
            <Dot color={result.ok ? DOT_OK : DOT_FAILED} />
            <span>{result.ok ? 'Ready' : `Not ready (${result.reason || 'unreachable'})`}</span>
        </div>
    );
};

export type InstalledModels = Record<ModelKind, ModelStatus | null>;

interface MainTabProps {
    translator: Translator;
    overlayVisible: boolean;
    models: InstalledModels | null;
    webReachability: {
        ocr?: ReachResult;
        translation?: ReachResult;
    } | null;
    onNavigateToTab: (tabId: string, scrollTargetId?: string) => void;
}

export const MainTab: VFC<MainTabProps> = ({ translator, overlayVisible, models, webReachability, onNavigateToTab }) => {
    const { settings, updateSetting } = useSettings();

    const ocrNeedsDownload =
        !!models && settings.ocrProvider === 'chrome_screen_ai' && !models.chrome_screen_ai?.downloaded;

    const translationNeedsDownload =
        settings.ocrProvider !== 'gemini_vision'
        && settings.translationProvider === 'nllb'
        && !!models && !models.nllb?.downloaded;

    const handleButtonClick = () => {
        if (overlayVisible) {
            translator.dismiss();
            closeAllSideMenus().catch(err => logger.error('MainTab', 'Closing the side menu failed', err));
            return;
        }
        if (ocrNeedsDownload) {
            onNavigateToTab('translation', 'chrome_screen_ai-action');
            return;
        }
        if (translationNeedsDownload) {
            onNavigateToTab('translation', 'nllb-action');
            return;
        }
        closeAllSideMenus()
            .then(() => translator.translateScreen())
            .catch(err => logger.error('MainTab', 'Screenshot failed', err));
    };

    const renderButtonContent = () => {
        if (overlayVisible) {
            return <span style={{ display: "inline-flex", alignItems: "center", gap: "8px" }}><BsXLg /> Close Overlay</span>;
        }
        if (ocrNeedsDownload || translationNeedsDownload) {
            return <span style={{ display: "inline-flex", alignItems: "center", gap: "8px" }}><HiInboxArrowDown size={20} /> Download required</span>;
        }
        return <span style={{ display: "inline-flex", alignItems: "center", gap: "8px" }}><BsTranslate /> Translate</span>;
    };

    return (
        <div>
            <PanelSection>
                <PanelSectionRow>
                    <ToggleField
                        label={settings.enabled ? "Plugin is enabled" : "Plugin is disabled"}
                        description="Toggle the functionality on or off"
                        checked={settings.enabled}
                        onChange={(value) => updateSetting('enabled', value, 'WinDecky Translator')}
                    />
                </PanelSectionRow>

                {settings.enabled && (
                    <>
                        <PanelSectionRow>
                            <ButtonItem
                                bottomSeparator="standard"
                                layout="below"
                                onClick={handleButtonClick}>
                                {renderButtonContent()}
                            </ButtonItem>
                        </PanelSectionRow>

                        <PanelSectionRow>
                            <div style={{ fontSize: '12px', marginTop: '8px' }}>
                                {settings.ocrProvider === 'gemini_vision' && (
                                    <div style={{ display: 'flex', alignItems: 'center', marginBottom: '4px' }}>
                                        <BsStars style={{ marginRight: '8px', color: '#aaa' }} />
                                        <span style={{ color: '#888' }}>Recognize + Translate:</span>
                                        <span style={{ marginLeft: '6px', fontWeight: 'bold' }}>Gemini</span>
                                    </div>
                                )}
                                {settings.ocrProvider !== 'gemini_vision' && (
                                    <div style={{ display: 'flex', alignItems: 'center', marginBottom: '4px' }}>
                                        <BsEye style={{ marginRight: '8px', color: '#aaa' }} />
                                        <span style={{ color: '#888' }}>Text Recognition:</span>
                                        <span style={{ marginLeft: '6px', fontWeight: 'bold' }}>
                                            {OCR_PROVIDER_LABELS[settings.ocrProvider]}
                                        </span>
                                    </div>
                                )}
                                {settings.ocrProvider === 'chrome_screen_ai' && (
                                    <div style={{ marginLeft: '22px', marginBottom: '6px' }}>
                                        {models?.chrome_screen_ai?.downloaded && (
                                            <div style={{ color: '#666', fontSize: '10px', marginBottom: '4px' }}>Engine: Chrome Screen AI</div>
                                        )}
                                        <div style={{ color: '#666', fontSize: '10px', display: 'flex', alignItems: 'center' }}>
                                            {models?.chrome_screen_ai?.downloading ? (
                                                <>
                                                    <Dot color={DOT_INSTALLING} />
                                                    <span>Installing...</span>
                                                </>
                                            ) : (
                                                <>
                                                    <Dot color={!!models?.chrome_screen_ai?.downloaded ? DOT_OK : DOT_FAILED} />
                                                    <span>{models?.chrome_screen_ai?.downloaded ? 'Ready' : 'Not ready (Engine not installed)'}</span>
                                                </>
                                            )}
                                        </div>
                                    </div>
                                )}
                                {settings.ocrProvider === 'google_cloud' && (
                                    <div style={{ marginLeft: '22px', marginBottom: '6px' }}>
                                        <ReachabilityRow result={webReachability?.ocr} expectedProvider="google_cloud" />
                                    </div>
                                )}
                                {settings.ocrProvider !== 'gemini_vision' && (
                                    <div style={{ display: 'flex', alignItems: 'center', marginBottom: '2px' }}>
                                        <BsTranslate style={{ marginRight: '8px', color: '#aaa' }} />
                                        <span style={{ color: '#888' }}>Translation:</span>
                                        <span style={{ marginLeft: '6px', fontWeight: 'bold' }}>
                                            {TRANSLATION_PROVIDER_LABELS[settings.translationProvider]}
                                            {settings.translationProvider === 'llm' && ` (${LLM_SERVICE_LABELS[settings.llmService] || settings.llmService})`}
                                        </span>
                                    </div>
                                )}
                                <div style={{ marginLeft: '22px', marginBottom: '6px' }}>
                                    {settings.ocrProvider === 'gemini_vision' && (
                                        <>
                                            <div style={{ color: '#666', fontSize: '10px' }}>
                                                Model: {settings.geminiModel.replace(/^gemini-/, '').split('-').map((w: string) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')}
                                            </div>
                                            <ReachabilityRow result={webReachability?.ocr} expectedProvider="gemini_vision" />
                                        </>
                                    )}
                                    {settings.ocrProvider !== 'gemini_vision' && settings.translationProvider === 'google_web' && (
                                        <>
                                            <div style={{ color: '#666', fontSize: '10px' }}>No API key needed</div>
                                            <ReachabilityRow result={webReachability?.translation} expectedProvider="google_web" />
                                        </>
                                    )}
                                    {settings.ocrProvider !== 'gemini_vision' && settings.translationProvider === 'llm' && (
                                        <>
                                            <div style={{ color: '#666', fontSize: '10px' }}>
                                                Model: {llmModel(settings) || 'not set'} · Google/Bing as fallback
                                            </div>
                                            <ReachabilityRow result={webReachability?.translation} expectedProvider="llm" />
                                        </>
                                    )}
                                    {settings.ocrProvider !== 'gemini_vision' && settings.translationProvider === 'google_cloud' && (
                                        <>
                                            <ReachabilityRow result={webReachability?.translation} expectedProvider="google_cloud" />
                                        </>
                                    )}
                                    {settings.ocrProvider !== 'gemini_vision' && settings.translationProvider === 'nllb' && (
                                        <>
                                            {models?.nllb?.downloaded && (
                                                <div style={{ color: '#666', fontSize: '10px' }}>Model: NLLB-200 1.3B</div>
                                            )}
                                            <div style={{ color: '#666', fontSize: '10px', display: 'flex', alignItems: 'center' }}>
                                                {models?.nllb?.downloading ? (
                                                    <>
                                                        <Dot color={DOT_INSTALLING} />
                                                        <span>Installing...</span>
                                                    </>
                                                ) : (
                                                    <>
                                                        <Dot color={!!models?.nllb?.downloaded ? DOT_OK : DOT_FAILED} />
                                                        <span>{models?.nllb?.downloaded ? 'Ready' : 'Not ready (Model not installed)'}</span>
                                                    </>
                                                )}
                                            </div>
                                        </>
                                    )}
                                </div>
                            </div>
                        </PanelSectionRow>
                    </>
                )}
            </PanelSection>
        </div>
    );
};
