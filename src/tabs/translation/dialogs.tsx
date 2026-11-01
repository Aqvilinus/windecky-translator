import { ModalRoot, DialogButton, TextField, Focusable } from "@decky/ui";
import { VFC, useState, useEffect, useRef } from "react";
import { backend } from "../../backend";
import { maskKey } from "../../settings";
import { HiKey } from "react-icons/hi2";

// The key button beside a provider that needs one: its dot says whether a key is set
export const KeyButton: VFC<{ hasKey: boolean; onClick: () => void }> = ({ hasKey, onClick }) => (
    <DialogButton onClick={onClick} style={{ minWidth: "40px", width: "40px", padding: "10px 0" }}>
        <div style={{ position: "relative", display: "inline-flex" }}>
            <HiKey />
            <div style={{ position: "absolute", bottom: "-8px", right: "-6px", width: "6px", height: "6px",
                          borderRadius: "50%", backgroundColor: hasKey ? "#4caf50" : "#ff6b6b" }} />
        </div>
    </DialogButton>
);

// Windows: Steam's text fields have no Paste in their right-click menu and a gamepad has no Ctrl+V, so the key
// dialogs get a Paste button that reads the Windows clipboard through the backend.
export const PasteField: VFC<{ onPaste: (text: string) => void; children: any }> = ({ onPaste, children }) => {
    const fieldRef = useRef<HTMLDivElement>(null);
    // the text field has its label above and some space below the input, so line the button up with the input itself
    const [inputBox, setInputBox] = useState<{ top: number; height: number } | null>(null);
    useEffect(() => {
        const input = fieldRef.current?.querySelector("input");
        if (!fieldRef.current || !input) return;
        const f = fieldRef.current.getBoundingClientRect(), i = input.getBoundingClientRect();
        if (i.height > 0) setInputBox({ top: Math.round(i.top - f.top), height: Math.round(i.height) });
    }, []);

    return (
        <Focusable style={{ display: "flex", gap: "8px", alignItems: "flex-start" }} flow-children="horizontal">
            <div ref={fieldRef} style={{ flex: 1, minWidth: 0 }}>{children}</div>
            <DialogButton
                style={{
                    width: "auto", minWidth: "90px", padding: "0 16px",
                    marginTop: inputBox ? `${inputBox.top}px` : undefined,
                    height: inputBox ? `${inputBox.height}px` : undefined,
                }}
                onClick={async () => {
                    const text = await backend.getClipboardText().catch(() => "");
                    if (text && text.trim()) onPaste(text.trim());
                }}
            >
                Paste
            </DialogButton>
        </Focusable>
    );
};

export const ApiKeyModal: VFC<{
    currentKey: string;
    onSave: (key: string) => void;
    closeModal?: () => void;
    title: string;
    description: string;
}> = ({ currentKey, onSave, closeModal, title, description }) => {
    const [apiKey, setApiKey] = useState(currentKey || "");

    return (
        <ModalRoot onCancel={closeModal} onEscKeypress={closeModal}>
            <div style={{ padding: "20px", minWidth: "400px" }}>
                <h2 style={{ marginBottom: "15px" }}>{title}</h2>
                <p style={{ marginBottom: "15px", color: "#aaa", fontSize: "13px" }}>
                    {description}
                </p>
                {currentKey && (
                    <p style={{ marginBottom: "10px", color: "#aaa", fontSize: "13px" }}>
                        Current key: <span style={{ fontFamily: "monospace", color: "#fff" }}>{maskKey(currentKey)}</span>
                    </p>
                )}
                <PasteField onPaste={setApiKey}>
                    <TextField
                        label="API Key"
                        value={apiKey}
                        bIsPassword={true}
                        bShowClearAction={true}
                        onChange={(e) => setApiKey(e.target.value)}
                    />
                </PasteField>
                <Focusable
                    style={{ display: "flex", gap: "10px", marginTop: "20px", justifyContent: "flex-end" }}
                >
                    <DialogButton onClick={closeModal}>
                        Cancel
                    </DialogButton>
                    <DialogButton
                        onClick={() => {
                            onSave(apiKey.trim());
                            closeModal?.();
                        }}
                    >
                        Save
                    </DialogButton>
                </Focusable>
            </div>
        </ModalRoot>
    );
};

// AI translation through a custom OpenAI-compatible server: address, optional key, model
export const CustomServerModal: VFC<{
    url: string;
    apiKey: string;
    model: string;
    onSave: (url: string, apiKey: string, model: string) => void;
    closeModal?: () => void;
}> = ({ url, apiKey, model, onSave, closeModal }) => {
    const [u, setU] = useState(url || "");
    const [k, setK] = useState(apiKey || "");
    const [m, setM] = useState(model || "");
    return (
        <ModalRoot onCancel={closeModal} onEscKeypress={closeModal}>
            <div style={{ padding: "20px", minWidth: "400px" }}>
                <h2 style={{ marginBottom: "15px" }}>Custom AI Server</h2>
                <p style={{ marginBottom: "15px", color: "#aaa", fontSize: "13px" }}>
                    Any OpenAI-compatible API, e.g. https://openrouter.ai/api/v1 or a local llama.cpp server at
                    http://127.0.0.1:8080/v1. The key can stay empty for local servers.
                </p>
                <PasteField onPaste={setU}><TextField label="Server Address" value={u} bShowClearAction={true} onChange={(e) => setU(e.target.value)} /></PasteField>
                <PasteField onPaste={setK}><TextField label="API Key" value={k} bIsPassword={true} bShowClearAction={true} onChange={(e) => setK(e.target.value)} /></PasteField>
                {apiKey && (
                    <p style={{ margin: "4px 0 10px", color: "#aaa", fontSize: "13px" }}>
                        Current key: <span style={{ fontFamily: "monospace", color: "#fff" }}>{maskKey(apiKey)}</span>
                    </p>
                )}
                <TextField label="Model" value={m} bShowClearAction={true} onChange={(e) => setM(e.target.value)} />
                <Focusable style={{ display: "flex", gap: "10px", marginTop: "20px", justifyContent: "flex-end" }}>
                    <DialogButton onClick={closeModal}>Cancel</DialogButton>
                    <DialogButton onClick={() => { onSave(u.trim(), k.trim(), m.trim()); closeModal?.(); }}>Save</DialogButton>
                </Focusable>
            </div>
        </ModalRoot>
    );
};
