import {
    ButtonItem,
    PanelSection,
    PanelSectionRow,
    ToggleField
} from "@decky/ui";

import { VFC } from "react";
import { OCR_ENGINE_LABELS, TRANSLATION_ENGINE_LABELS } from "../providers";
import { BsTranslate, BsXLg, BsEye, BsStars } from "react-icons/bs";
import { HiInboxArrowDown } from "react-icons/hi2";
import { useSettings } from "../SettingsContext";
import type { ModelKind, ModelStatus } from "../backend";
import { GameTranslatorLogic } from "../Translator";
import { LLM_BACKEND_LABELS, llmModel } from "../llm";
import { logger } from "../log";
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

export type InstalledModels = Record<ModelKind, ModelStatus | null>;

interface TabMainProps {
    logic: GameTranslatorLogic;
    overlayVisible: boolean;
    models: InstalledModels | null;
    webReachability: {
        ocr?: ReachResult;
        translation?: ReachResult;
    } | null;
    onNavigateToTab: (tabId: string, scrollTargetId?: string) => void;
}

export const TabMain: VFC<TabMainProps> = ({ logic, overlayVisible, models, webReachability, onNavigateToTab }) => {
    const { settings, updateSetting } = useSettings();

    const ocrNeedsDownload =
        !!models && settings.ocrProvider === 'chromescreenai' && !models.chromescreenai?.downloaded;

    const translationNeedsDownload =
        settings.ocrProvider !== 'gemini_vision'
        && settings.translationProvider === 'ct2'
        && !!models && !models.nllb?.downloaded;

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
                                            {OCR_ENGINE_LABELS[settings.ocrProvider]}
                                        </span>
                                    </div>
                                )}
                                {settings.ocrProvider === 'chromescreenai' && (
                                    <div style={{ marginLeft: '22px', marginBottom: '6px' }}>
                                        {models?.chromescreenai?.downloaded && (
                                            <div style={{ color: '#666', fontSize: '10px', marginBottom: '4px' }}>Engine: Chrome Screen AI</div>
                                        )}
                                        <div style={{ color: '#666', fontSize: '10px', display: 'flex', alignItems: 'center' }}>
                                            {models?.chromescreenai?.downloading ? (
                                                <>
                                                    <InstallingDot />
                                                    <span>Installing...</span>
                                                </>
                                            ) : (
                                                <>
                                                    <StatusDot ok={!!models?.chromescreenai?.downloaded} />
                                                    <span>{models?.chromescreenai?.downloaded ? 'Ready' : 'Not ready (Engine not installed)'}</span>
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
                                {settings.ocrProvider !== 'gemini_vision' && (
                                    <div style={{ display: 'flex', alignItems: 'center', marginBottom: '2px' }}>
                                        <BsTranslate style={{ marginRight: '8px', color: '#aaa' }} />
                                        <span style={{ color: '#888' }}>Translation:</span>
                                        <span style={{ marginLeft: '6px', fontWeight: 'bold' }}>
                                            {TRANSLATION_ENGINE_LABELS[settings.translationProvider]}
                                            {settings.translationProvider === 'llm' && ` (${LLM_BACKEND_LABELS[settings.llmBackend] || settings.llmBackend})`}
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
                                            {models?.nllb?.downloaded && (
                                                <div style={{ color: '#666', fontSize: '10px' }}>Model: NLLB-200 1.3B</div>
                                            )}
                                            <div style={{ color: '#666', fontSize: '10px', display: 'flex', alignItems: 'center' }}>
                                                {models?.nllb?.downloading ? (
                                                    <>
                                                        <InstallingDot />
                                                        <span>Installing...</span>
                                                    </>
                                                ) : (
                                                    <>
                                                        <StatusDot ok={!!models?.nllb?.downloaded} />
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
