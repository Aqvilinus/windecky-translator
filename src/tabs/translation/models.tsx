// Model choice for Gemini Vision and AI translation
import { PanelSectionRow, Dropdown, DialogButton, Field, Focusable, type SingleDropdownOption } from "@decky/ui";
import { VFC, useState, useEffect, useRef } from "react";
import { BsArrowRepeat } from "react-icons/bs";

export const llmBackendOptions = [
    { label: <span>Gemini</span>, data: "gemini" },
    { label: <span>Groq</span>, data: "groq" },
    { label: <span>Custom server</span>, data: "custom" },
];

export const modelOption = (name: string): SingleDropdownOption =>
    ({ label: <span>{name.replace(/^models\//, "")}</span>, data: name });

// Model dropdown with a refresh button. Once canList is set the list comes from listModels, until then
// (and when it comes back empty) the fallback options show. knownOnly: the service's list only narrows
// the fallback, and a selection it lacks moves to the first one left; otherwise the service's names
// replace the fallback and the selected model always stays listed.
export const ModelPicker: VFC<{
    label: string;
    source?: string;
    listModels: (source: string) => Promise<string[] | null | undefined>;
    fallback: SingleDropdownOption[];
    knownOnly?: boolean;
    canList: boolean;
    selectedModel: string;
    placeholder?: string;
    onChange: (model: string) => void;
}> = ({ label, source = "", listModels, fallback, knownOnly, canList, selectedModel, placeholder, onChange }) => {
    const [available, setAvailable] = useState<string[]>([]);
    const [loading, setLoading] = useState(false);
    // the source the newest request was for: a slow reply for the previous one must not fill this list
    const current = useRef(source);
    current.current = source;

    const refresh = async () => {
        if (!canList) return;
        const asked = source;
        setLoading(true);
        let models: string[] = [];
        try {
            models = await listModels(asked) || [];
        } catch {
            models = [];
        }
        if (current.current !== asked) return;
        if (!knownOnly) {
            setAvailable(models);
        } else {
            const usable = fallback.filter(o => models.includes(o.data));
            // nothing known in the reply (or an error): keep the list as it is
            if (usable.length) {
                setAvailable(models);
                if (!models.includes(selectedModel)) onChange(usable[0].data);
            }
        }
        setLoading(false);
    };

    useEffect(() => { setAvailable([]); setLoading(false); refresh(); }, [source, canList]);

    let options: SingleDropdownOption[];
    if (knownOnly) {
        const usable = fallback.filter(o => available.includes(o.data));
        options = usable.length ? usable : fallback;
    } else {
        const names = Array.from(new Set([
            ...(selectedModel ? [selectedModel] : []),
            ...(available.length ? available : fallback.map(o => o.data as string)),
        ]));
        options = names.map(n => fallback.find(o => o.data === n) || modelOption(n));
    }
    return (
        <PanelSectionRow>
            <Field label={label} childrenContainerWidth="max" childrenLayout="below" focusable={false}>
                <style>{`@keyframes gemini-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
                <Focusable style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                    <div style={{ flex: 1 }}>
                        <Dropdown
                            rgOptions={options}
                            selectedOption={selectedModel}
                            strDefaultLabel={placeholder}
                            onChange={(option) => onChange(option.data)}
                        />
                    </div>
                    <DialogButton
                        onClick={refresh}
                        disabled={loading || !canList}
                        style={{ minWidth: "40px", width: "40px", padding: "10px 0" }}
                    >
                        <BsArrowRepeat style={loading ? { animation: "gemini-spin 1s linear infinite" } : {}} />
                    </DialogButton>
                </Focusable>
            </Field>
        </PanelSectionRow>
    );
};

export const knownGeminiModels: SingleDropdownOption[] = [
    { label: <span>3.5 Flash</span>, data: "gemini-3.5-flash" },
    { label: <span>Flash Lite (latest)</span>, data: "gemini-flash-lite-latest" },
    { label: <span>2.5 Flash</span>, data: "gemini-2.5-flash" },
    { label: <span>2.5 Flash Lite</span>, data: "gemini-2.5-flash-lite" },
    { label: <span>3 Flash (Preview)</span>, data: "gemini-3-flash-preview" },
    { label: <span>3 Flash</span>, data: "gemini-3-flash" },
    { label: <span>3.1 Flash Lite (Preview)</span>, data: "gemini-3.1-flash-lite-preview" },
    { label: <span>3.1 Flash Lite</span>, data: "gemini-3.1-flash-lite" },
];
