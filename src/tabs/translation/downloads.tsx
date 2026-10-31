// Downloadable models (main.py get_model_status & co.) and the engines' quality/speed ratings
import { DialogButton, ProgressBar } from "@decky/ui";
import { VFC, useState, useEffect, useRef, useCallback, RefObject } from "react";
import { backend, ModelKind } from "../../backend";
import { HiInboxArrowDown, HiTrash, HiXMark } from "react-icons/hi2";
import { formatBytes } from "./languages";

export type ModelDownloadState = {
    status: any;
    isDownloading: boolean;
    isDownloaded: boolean;
    progressPct: number;
    statusColor: string;
    statusText: string;
    ActionIcon: typeof HiInboxArrowDown;
    onActionClick: () => void;
};

export function formatApproxSize(mb: number): string {
    if (mb >= 1000) {
        return `${(mb / 1024).toFixed(1)} GB`;
    }
    return `${Math.round(mb)} MB`;
}


export function useModelDownload(kind: ModelKind, approxMb: number): ModelDownloadState {
    const [status, setStatus] = useState<any>({
        downloaded: false, size: 0, approx_size_mb: approxMb,
        downloading: false, progress: 0, error: null,
    });
    const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

    const refresh = useCallback(async () => {
        try {
            const s = await backend.getModelStatus(kind);
            if (s) setStatus(s);
        } catch (e) { /* ignore */ }
    }, [kind]);

    useEffect(() => { refresh(); }, []);

    useEffect(() => {
        if (status.downloading) {
            pollRef.current = setInterval(refresh, 500);
        } else if (pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
        }
        return () => {
            if (pollRef.current) clearInterval(pollRef.current);
        };
    }, [status.downloading, refresh]);

    const handleDownload = async () => {
        await backend.clearModelError(kind);
        const started = await backend.downloadModel(kind);
        if (started) {
            setStatus((prev: any) => ({ ...prev, downloading: true, progress: 0, error: null }));
        }
    };
    const handleCancel = async () => { await backend.cancelModelDownload(kind); };
    const handleDelete = async () => { await backend.deleteModel(kind); refresh(); };

    const isDownloading = status.downloading;
    const isDownloaded = status.downloaded;
    const progressPct = Math.round((status.progress || 0) * 100);
    const statusColor = isDownloading ? "#ffa726" : isDownloaded ? "#4caf50" : "#ff6b6b";
    const installedSize = status.size ? ` (${formatBytes(status.size)})` : '';
    const approxSize = status.approx_size_mb ? ` (${formatApproxSize(status.approx_size_mb)})` : '';
    const statusText = isDownloading
        ? `downloading ${progressPct}%`
        : isDownloaded
            ? `Installed${installedSize}`
            : `Not installed${approxSize}`;
    const ActionIcon = isDownloading ? HiXMark : isDownloaded ? HiTrash : HiInboxArrowDown;
    const onActionClick = isDownloading ? handleCancel : isDownloaded ? handleDelete : handleDownload;

    return { status, isDownloading, isDownloaded, progressPct, statusColor, statusText, ActionIcon, onActionClick };
}

export function useChromeScreenAIStatus() {
    return useModelDownload('chromescreenai', 80);  // until the backend answers (screenai_downloader.py)
}

export function useNllbModelStatus() {
    return useModelDownload('nllb', 1410);
}

export const ModelActionButton: VFC<{
    state: ModelDownloadState;
    actionRef?: RefObject<HTMLDivElement>;
}> = ({ state, actionRef }) => {
    const { ActionIcon, onActionClick, isDownloaded, isDownloading } = state;
    const needsDownload = !isDownloaded && !isDownloading;
    return (
        <>
            <style>{`@keyframes dt-download-pulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(255, 255, 255, 0); } 50% { box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.45); } }`}</style>
            <DialogButton
                ref={actionRef}
                onClick={onActionClick}
                style={{
                    minWidth: "40px",
                    width: "40px",
                    padding: "10px 0",
                    animation: needsDownload ? "dt-download-pulse 1.6s ease-in-out infinite" : undefined,
                }}
            >
                <ActionIcon style={{ transform: "scale(1.25) translateY(1px)" }} />
            </DialogButton>
        </>
    );
};

export const ModelStatusIndicator: VFC<{ state: ModelDownloadState }> = ({ state }) => (
    <div style={{
        display: "flex",
        alignItems: "center",
        gap: "6px",
        marginBottom: "6px",
        marginLeft: "26px",
        fontSize: "11px",
    }}>
        <div style={{
            width: "6px",
            height: "6px",
            borderRadius: "50%",
            backgroundColor: state.statusColor,
            flexShrink: 0,
        }} />
        <span style={{ color: state.statusColor }}>{state.statusText}</span>
    </div>
);

export const ModelHeadingProgressBar: VFC<{ state: ModelDownloadState }> = ({ state }) => (
    state.isDownloading ? (
        <div style={{ margin: "2px 0 4px 26px" }}>
            <ProgressBar nProgress={state.progressPct} />
        </div>
    ) : null
);

export const ModelDownloadError: VFC<{ state: ModelDownloadState }> = ({ state }) => (
    state.status.error && !state.isDownloading ? (
        <div style={{
            color: "#ff6b6b",
            fontSize: "11px",
            marginTop: "6px",
            marginBottom: "4px",
            whiteSpace: "normal",
            wordBreak: "break-word",
        }}>
            {state.status.error}
        </div>
    ) : null
);

export const StarRating: VFC<{ label: string; filled: number; total?: number }> = ({ label, filled, total = 3 }) => (
    <span style={{ display: "flex", alignItems: "center", gap: "4px" }}>
        <span style={{ color: "#888", fontSize: "11px" }}>{label}</span>
        {Array.from({ length: total }, (_, i) => (
            <svg key={i} width="10" height="10" viewBox="0 0 24 24" fill={i < filled ? "#ffa726" : "#444"}>
                <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z"/>
            </svg>
        ))}
    </span>
);

export const ProviderRating: VFC<{ quality: number; speed: number }> = ({ quality, speed }) => (
    <div style={{ display: "flex", gap: "16px", marginBottom: "6px" }}>
        <StarRating label="Quality" filled={quality} />
        <StarRating label="Speed" filled={speed} />
    </div>
);
