// src/tabs/TabMain.tsx - Main tab with enable toggle and translate button

import {
    ButtonItem,
    PanelSection,
    PanelSectionRow,
    ToggleField
} from "@decky/ui";

import { VFC } from "react";
import { BsTranslate, BsXLg, BsEye, BsStars } from "react-icons/bs";
import { HiInboxArrowDown } from "react-icons/hi2";
import { useSettings } from "../SettingsContext";
import { GameTranslatorLogic } from "../Translator";
import { LLM_BACKEND_LABELS, llmModel } from "../llm";
import { logger } from "../Logger";
import { closeAllSideMenus } from "../windows";

const StatusDot: VFC<{ ok: boolean }> = ({ ok }) => (
    <span style={{
        display: 'inline-block',
        width: '5px',
        height: '5px',
        borderRadius: '50%',
        backgroundColor: ok ? '#4caf50' : '#ff6b6b',
        marginRight: '6px',
        flexShrink: 0
    }} />
);

const PendingDot: VFC = () => (
    <span style={{
        display: 'inline-block',
        width: '5px',
        height: '5px',
        borderRadius: '50%',
        backgroundColor: '#888',
        marginRight: '6px',
        flexShrink: 0
    }} />
);

const InstallingDot: VFC = () => (
    <span style={{
        display: 'inline-block',
        width: '5px',
        height: '5px',
        borderRadius: '50%',
        backgroundColor: '#ffa726',
        marginRight: '6px',
        flexShrink: 0
    }} />
);

type ReachResult = { ok: boolean; reason: string; provider: string } | null | undefined;

const ReachabilityRow: VFC<{ result: ReachResult; expectedProvider: string }> = ({ result, expectedProvider }) => {
    if (!result || result.provider !== expectedProvider) {
        return (
            <div style={{ color: '#666', fontSize: '10px', display: 'flex', alignItems: 'center' }}>
                <PendingDot />
                <span>Checking...</span>
            </div>
        );
    }
    return (
        <div style={{ color: '#666', fontSize: '10px', display: 'flex', alignItems: 'center' }}>
            <StatusDot ok={result.ok} />
            <span>{result.ok ? 'Ready' : `Not ready (${result.reason || 'unreachable'})`}</span>
        </div>
    );
};

interface TabMainProps {
    logic: GameTranslatorLogic;
    overlayVisible: boolean;
    providerStatus: any;
    webReachability: {
        ocr?: ReachResult;
        translation?: ReachResult;
    } | null;
    onNavigateToTab: (tabId: string, scrollTargetId?: string) => void;
}

export const TabMain: VFC<TabMainProps> = ({ logic, overlayVisible, providerStatus, webReachability, onNavigateToTab }) => {
    const { settings, updateSetting } = useSettings();

    const ocrNeedsDownload =
        !!providerStatus
        && settings.ocrProvider === 'chromescreenai' && !providerStatus.chromescreenai_downloaded;

    const translationNeedsDownload =
        settings.ocrProvider !== 'gemini_vision'
        && settings.translationProvider === 'ct2'
        && !!providerStatus
        && !providerStatus.nllb_downloaded;

    const handleButtonClick = () => {
        if (overlayVisible) {
            logic.dismiss();
            closeAllSideMenus().catch(err => logger.error('TabMain', 'Closing the side menu failed', err));
            return;
        }
        if (ocrNeedsDownload) {
            onNavigateToTab('translation', 'chromescreenai-action');
            return;
        }
        if (translationNeedsDownload) {
            onNavigateToTab('translation', 'ct2-action');
            return;
        }
        // close the side menu (in every Steam window) and wait until it is gone before taking the screenshot
        closeAllSideMenus()
            .then(() => logic.takeScreenshotAndTranslate())
            .catch(err => logger.error('TabMain', 'Screenshot failed', err));
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
                        onChange={(value) => updateSetting('enabled', value, 'Decky Translator')}
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

                        {/* Provider Status */}
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
                                            {settings.ocrProvider === 'chromescreenai' ? 'On-Device' :
                                             settings.ocrProvider === 'windows_ocr' ? 'On-Device (Windows)' :
                                             settings.ocrProvider === 'ocrspace' ? 'OCR.space' : 'Google Cloud'}
                                        </span>
                                    </div>
                                )}
                                {settings.ocrProvider === 'chromescreenai' && (
                                    <div style={{ marginLeft: '22px', marginBottom: '6px' }}>
                                        {providerStatus?.chromescreenai_downloaded && (
                                            <div style={{ color: '#666', fontSize: '10px', marginBottom: '4px' }}>Engine: Chrome Screen AI</div>
                                        )}
                                        <div style={{ color: '#666', fontSize: '10px', display: 'flex', alignItems: 'center' }}>
                                            {providerStatus?.chromescreenai_downloading ? (
                                                <>
                                                    <InstallingDot />
                                                    <span>Installing...</span>
                                                </>
                                            ) : (
                                                <>
                                                    <StatusDot ok={!!providerStatus?.chromescreenai_downloaded} />
                                                    <span>{providerStatus?.chromescreenai_downloaded ? 'Ready' : 'Not ready (Engine not installed)'}</span>
                                                </>
                                            )}
                                        </div>
                                    </div>
                                )}
                                {settings.ocrProvider === 'googlecloud' && (
                                    <div style={{ marginLeft: '22px', marginBottom: '6px' }}>
                                        <ReachabilityRow result={webReachability?.ocr} expectedProvider="googlecloud" />
                                    </div>
                                )}
                                {settings.ocrProvider === 'ocrspace' && (
                                    <div style={{ marginLeft: '22px', marginBottom: '6px' }}>
                                        <div style={{ color: '#666', fontSize: '10px', marginBottom: '4px' }}>Free, no API key needed</div>
                                        {providerStatus?.ocr_usage && (
                                            <>
                                                <div style={{
                                                    display: 'flex',
                                                    justifyContent: 'space-between',
                                                    alignItems: 'center',
                                                    marginBottom: '3px'
                                                }}>
                                                    <span style={{ color: '#666', fontSize: '10px' }}>
                                                        10 min limit:
                                                    </span>
                                                    <span style={{
                                                        fontSize: '10px',
                                                        color: providerStatus.ocr_usage.rate_remaining <= 2 ? '#ff6b6b' : '#888'
                                                    }}>
                                                        {providerStatus.ocr_usage.rate_remaining}/{providerStatus.ocr_usage.rate_limit}
                                                    </span>
                                                </div>
                                                <div style={{
                                                    height: '3px',
                                                    backgroundColor: 'rgba(255,255,255,0.1)',
                                                    borderRadius: '2px',
                                                    overflow: 'hidden',
                                                    marginBottom: '4px'
                                                }}>
                                                    <div style={{
                                                        height: '100%',
                                                        width: `${(providerStatus.ocr_usage.rate_remaining / providerStatus.ocr_usage.rate_limit) * 100}%`,
                                                        backgroundColor: providerStatus.ocr_usage.rate_remaining <= 2
                                                            ? '#ff6b6b'
                                                            : providerStatus.ocr_usage.rate_remaining <= 5
                                                                ? '#ffa726'
                                                                : '#4caf50',
                                                        borderRadius: '2px',
                                                        transition: 'width 0.3s ease'
                                                    }} />
                                                </div>
                                                {providerStatus.ocr_usage.rate_remaining === 0 && providerStatus.ocr_usage.rate_reset_seconds > 0 && (
                                                    <div style={{ color: '#ff6b6b', fontSize: '10px', marginBottom: '4px' }}>
                                                        Rate limit exceeded - resets in {Math.ceil(providerStatus.ocr_usage.rate_reset_seconds / 60)} min
                                                    </div>
                                                )}

                                                <div style={{
                                                    display: 'flex',
                                                    justifyContent: 'space-between',
                                                    alignItems: 'center',
                                                    marginBottom: '3px'
                                                }}>
                                                    <span style={{ color: '#666', fontSize: '10px' }}>
                                                        Daily limit:
                                                    </span>
                                                    <span style={{
                                                        fontSize: '10px',
                                                        color: providerStatus.ocr_usage.remaining < 50 ? '#ff6b6b' : '#888'
                                                    }}>
                                                        {providerStatus.ocr_usage.remaining}/{providerStatus.ocr_usage.limit}
                                                    </span>
                                                </div>
                                                <div style={{
                                                    height: '3px',
                                                    backgroundColor: 'rgba(255,255,255,0.1)',
                                                    borderRadius: '2px',
                                                    overflow: 'hidden',
                                                    marginBottom: '4px'
                                                }}>
                                                    <div style={{
                                                        height: '100%',
                                                        width: `${(providerStatus.ocr_usage.remaining / providerStatus.ocr_usage.limit) * 100}%`,
                                                        backgroundColor: providerStatus.ocr_usage.remaining < 50
                                                            ? '#ff6b6b'
                                                            : providerStatus.ocr_usage.remaining < 100
                                                                ? '#ffa726'
                                                                : '#4caf50',
                                                        borderRadius: '2px',
                                                        transition: 'width 0.3s ease'
                                                    }} />
                                                </div>
                                                {providerStatus.ocr_usage.remaining < 50 && (
                                                    <div style={{ color: '#ff6b6b', fontSize: '10px', marginBottom: '4px' }}>
                                                        Low daily requests remaining
                                                    </div>
                                                )}
                                            </>
                                        )}
                                        <ReachabilityRow result={webReachability?.ocr} expectedProvider="ocrspace" />
                                    </div>
                                )}
                                {settings.ocrProvider !== 'gemini_vision' && (
                                    <div style={{ display: 'flex', alignItems: 'center', marginBottom: '2px' }}>
                                        <BsTranslate style={{ marginRight: '8px', color: '#aaa' }} />
                                        <span style={{ color: '#888' }}>Translation:</span>
                                        <span style={{ marginLeft: '6px', fontWeight: 'bold' }}>
                                            {settings.translationProvider === 'googlecloud' ? 'Google Cloud' :
                                             settings.translationProvider === 'ct2' ? 'On-Device' :
                                             settings.translationProvider === 'llm' ? `AI (${LLM_BACKEND_LABELS[settings.llmBackend] || settings.llmBackend})` :
                                             'Google Translate'}
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
                                    {settings.ocrProvider !== 'gemini_vision' && settings.translationProvider === 'freegoogle' && (
                                        <>
                                            <div style={{ color: '#666', fontSize: '10px' }}>No API key needed</div>
                                            <ReachabilityRow result={webReachability?.translation} expectedProvider="freegoogle" />
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
                                    {settings.ocrProvider !== 'gemini_vision' && settings.translationProvider === 'googlecloud' && (
                                        <>
                                            <ReachabilityRow result={webReachability?.translation} expectedProvider="googlecloud" />
                                        </>
                                    )}
                                    {settings.ocrProvider !== 'gemini_vision' && settings.translationProvider === 'ct2' && (
                                        <>
                                            {providerStatus?.nllb_downloaded && (
                                                <div style={{ color: '#666', fontSize: '10px' }}>Model: NLLB-200 1.3B</div>
                                            )}
                                            <div style={{ color: '#666', fontSize: '10px', display: 'flex', alignItems: 'center' }}>
                                                {providerStatus?.nllb_downloading ? (
                                                    <>
                                                        <InstallingDot />
                                                        <span>Installing...</span>
                                                    </>
                                                ) : (
                                                    <>
                                                        <StatusDot ok={!!providerStatus?.nllb_downloaded} />
                                                        <span>{providerStatus?.nllb_downloaded ? 'Ready' : 'Not ready (Model not installed)'}</span>
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
