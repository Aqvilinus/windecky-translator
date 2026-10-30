// src/tabs/TabControls.tsx - the shortcut, display and behavior settings, and debug

import {
    PanelSection,
    PanelSectionRow,
    ToggleField,
    SliderField,
    Field
} from "@decky/ui";

import { VFC, useEffect, useState } from "react";
import { call } from "@decky/api";
import { useSettings } from "../SettingsContext";
import { WINDOWS_HOTKEY } from "../windows";

// The Windows parts' state (main.py get_windows_status), shown in debug mode
const WindowsStatus: VFC = () => {
    const [status, setStatus] = useState<any>(null);
    useEffect(() => {
        const refresh = () => call<[], any>('get_windows_status').then(setStatus).catch(() => setStatus(null));
        refresh();
        const id = setInterval(refresh, 1000);
        return () => clearInterval(id);
    }, []);
    if (!status) return null;
    const hotkey = status.hotkey || {};
    const [pid, exe, isGame] = hotkey.foreground || [];
    const capture = status.capture || {};
    const row = (name: string, value: string) => (
        <div><span style={{ color: '#888' }}>{name}:</span> {value}</div>
    );
    return (
        <div className="dt-debug-panel" style={{
            backgroundColor: 'rgba(0,0,0,0.4)', padding: '12px', borderRadius: '6px', fontSize: '11px',
            fontFamily: 'monospace', border: '1px solid rgba(255,255,255,0.1)', display: 'grid', gap: '3px'
        }}>
            {row('Shortcut', hotkey.registered ? `${hotkey.hotkey} active` : hotkey.error ? `taken (error ${hotkey.error})` : 'inactive')}
            {row('In front', exe ? `${exe} (${pid})${isGame ? ', a game' : ''}` : '-')}
            {status.overlay_error && row('Overlay', status.overlay_error)}
            {row('Last capture', capture.width ? `${capture.width}x${capture.height} at (${capture.left},${capture.top})` : '-')}
        </div>
    );
};

export const TabControls: VFC = () => {
    const { settings, updateSetting } = useSettings();

    return (
        <div>
            <PanelSection title="Control">
                <PanelSectionRow>
                    <Field
                        label="Shortcut"
                        description="Press in a game to translate, again to close. To use a controller, map it to a button in your handheld's app (e.g. OneXConsole) or in Steam Input"
                        focusable={true}
                    >
                        <span style={{ fontWeight: "bold", whiteSpace: "nowrap" }}>{WINDOWS_HOTKEY}</span>
                    </Field>
                </PanelSectionRow>
            </PanelSection>

            <PanelSection title="Display">
                <PanelSectionRow>
                    <SliderField
                        value={settings.fontScale}
                        max={3}
                        min={1}
                        step={0.1}
                        label="Font Scaling"
                        description="Increase if translated text is too small. Can be useful for large external monitors"
                        showValue={true}
                        valueSuffix="x"
                        onChange={(value) => {
                            const rounded = Math.round(value * 10) / 10;
                            updateSetting('fontScale', rounded, 'Font scale');
                        }}
                    />
                </PanelSectionRow>
            </PanelSection>

            <PanelSection title="Behavior">
                <PanelSectionRow>
                    <ToggleField
                        checked={settings.pauseGameOnOverlay}
                        label="Pause Game While Translating"
                        description={<>Pauses the active game and allows you to read the text more thoughtfully. The game is resumed when overlay is dismissed.<br /><br />Doesn't work well with game streaming (moonlight, geforce now, remote play, etc)</>}
                        onChange={(value) => {
                            updateSetting('pauseGameOnOverlay', value, 'Pause game while translating');
                        }}
                    />
                </PanelSectionRow>
            </PanelSection>

            <PanelSection title="Miscellaneous">
                <PanelSectionRow>
                    <ToggleField
                        label="Debug Mode"
                        description="Enable verbose console logging and diagnostics panel"
                        checked={settings.debugMode}
                        onChange={(value) => updateSetting('debugMode', value, 'Debug mode')}
                    />
                </PanelSectionRow>
                {settings.debugMode && (
                    <PanelSectionRow>
                        <Field focusable={true} childrenContainerWidth="max">
                            <WindowsStatus />
                        </Field>
                    </PanelSectionRow>
                )}
            </PanelSection>
        </div>
    );
};
