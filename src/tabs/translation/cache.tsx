// The translation cache: its entries in a dialog
import { ModalRoot, DialogButton, Focusable } from "@decky/ui";
import { VFC, useState, useEffect, useRef } from "react";
import { OCR_ENGINE_LABELS, TRANSLATION_ENGINE_LABELS } from "../../providers";
import { backend } from "../../backend";
import { HiTrash, HiXCircle, HiExclamationTriangle } from "react-icons/hi2";
import { languageOptions } from "./languages";

// who translated a cached line: a translation engine, or Gemini Vision (OCR and translation in one)
export const cacheProviderLabel = (p: string) =>
    ({ ...TRANSLATION_ENGINE_LABELS, gemini_vision: OCR_ENGINE_LABELS.gemini_vision } as Record<string, string>)[p] || p || "?";

export const cacheLangFlag = (code: string) => {
    const opt = languageOptions.find(o => o.data === code);
    return opt ? opt.label.split(" ")[0] : code;
};

// compare by word content only, ignoring spacing, punctuation and case
export const cacheWordContent = (s: string) => (s || "").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "");
export const cacheSameText = (a: string, b: string) => cacheWordContent(a) === cacheWordContent(b);

// matches the backend MAX_ROWS eviction cap, so we load every cached entry
export const CACHE_ENTRY_LIMIT = 50000;
export const CACHE_PAGE_SIZE = 100;

export const CacheEntriesModal: VFC<{ closeModal?: () => void; onCleared?: () => void }> = ({ closeModal, onCleared }) => {
    const [entries, setEntries] = useState<any[] | null>(null);
    const [filter, setFilter] = useState<"all" | "unique" | "identical">("all");
    const [page, setPage] = useState(0);
    const [confirmClear, setConfirmClear] = useState(false);
    const wrapRef = useRef<HTMLDivElement>(null);
    const trackRef = useRef<HTMLDivElement>(null);
    const thumbRef = useRef<HTMLDivElement>(null);

    const cycleFilter = () => {
        const order = ["unique", "identical", "all"] as const;
        setFilter(f => order[(order.indexOf(f) + 1) % order.length]);
        setPage(0);
        setConfirmClear(false);
    };

    useEffect(() => {
        backend.getTranslationCacheEntries(CACHE_ENTRY_LIMIT)
            .then((rows) => setEntries(rows || []))
            .catch(() => setEntries([]));
    }, []);

    const all = entries || [];
    const shown = filter === "all"
        ? all
        : all.filter(e => cacheSameText(e.source, e.translation) === (filter === "identical"));
    const totalPages = Math.max(1, Math.ceil(shown.length / CACHE_PAGE_SIZE));
    const pageItems = shown.slice(page * CACHE_PAGE_SIZE, (page + 1) * CACHE_PAGE_SIZE);

    useEffect(() => {
        if (page >= totalPages) setPage(totalPages - 1);
    }, [totalPages, page]);

    useEffect(() => {
        const sc = wrapRef.current?.querySelector(".dt-cache-scroll") as HTMLElement | null;
        const track = trackRef.current;
        const thumbEl = thumbRef.current;
        if (!sc || !track || !thumbEl) return;
        const update = () => {
            const h = sc.clientHeight;
            if (!sc.scrollHeight || sc.scrollHeight <= h) {
                track.style.display = "none";
                return;
            }
            track.style.display = "block";
            const height = Math.max(24, h * h / sc.scrollHeight);
            const range = sc.scrollHeight - h;
            const top = range > 0 ? (sc.scrollTop / range) * (h - height) : 0;
            thumbEl.style.height = `${height}px`;
            thumbEl.style.transform = `translateY(${top}px)`;
        };
        update();
        sc.addEventListener("scroll", update);
        return () => sc.removeEventListener("scroll", update);
    }, [entries, filter, page]);

    const removeEntry = async (e: any) => {
        await backend.deleteTranslationCacheEntry(e.sourceLang, e.targetLang, e.source);
        setEntries(prev => prev ? prev.filter(x => !(x.sourceLang === e.sourceLang && x.targetLang === e.targetLang && x.source === e.source)) : prev);
    };

    // first press arms the button, second press actually clears
    const handleClear = async () => {
        if (!confirmClear) {
            setConfirmClear(true);
            return;
        }
        setConfirmClear(false);
        await backend.clearTranslationCache();
        setEntries([]);
        onCleared?.();
    };

    const onThumbDown = (e: any) => {
        e.preventDefault();
        const sc = wrapRef.current?.querySelector(".dt-cache-scroll") as HTMLElement | null;
        if (!sc) return;
        const startY = e.clientY;
        const startScroll = sc.scrollTop;
        const track = sc.clientHeight;
        const thumbH = Math.max(24, track * track / sc.scrollHeight);
        const travel = track - thumbH;
        const scrollRange = sc.scrollHeight - track;
        const onMove = (ev: MouseEvent) => {
            if (travel > 0) sc.scrollTop = startScroll + (ev.clientY - startY) * (scrollRange / travel);
        };
        const onUp = () => {
            document.removeEventListener("mousemove", onMove);
            document.removeEventListener("mouseup", onUp);
        };
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
    };

    const pagerButton = (label: string, enabled: boolean, onClick: () => void) => {
        const base = { minWidth: "auto", width: "auto", padding: "4px 14px", fontSize: "12px" };
        return enabled
            ? <DialogButton onClick={onClick} style={base}>{label}</DialogButton>
            : <div style={{ ...base, opacity: 0.3, color: "#8b929a", display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(255,255,255,0.05)", borderRadius: "2px" }}>{label}</div>;
    };

    return (
        <ModalRoot onCancel={closeModal} onEscKeypress={closeModal}>
            <Focusable
                style={{ display: "flex", flexDirection: "column", maxHeight: "70vh", boxSizing: "border-box", minWidth: "540px" }}
            >
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "10px", marginBottom: "10px", flexShrink: 0 }}>
                    <div style={{ fontSize: "16px", fontWeight: "bold" }}>{filter === "all" ? "All" : filter === "unique" ? "Unique" : "Identical"} Cached Translations{entries !== null && <span style={{ color: "rgba(255,255,255,0.45)" }}> ({shown.length})</span>}</div>
                    {all.length > 0 && (
                        <Focusable style={{ display: "flex", gap: "8px", alignItems: "center", flex: "0 0 auto" }}>
                            <DialogButton
                                onClick={cycleFilter}
                                style={{ width: "auto", minWidth: "auto", height: "32px", padding: "0 12px", whiteSpace: "nowrap", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "13px" }}
                            >
                                Showing: {filter === "all" ? "all" : `${filter} only`}
                            </DialogButton>
                            <DialogButton
                                onClick={handleClear}
                                style={{ width: "auto", minWidth: "auto", height: "32px", padding: "0 12px", whiteSpace: "nowrap", display: "flex", alignItems: "center", justifyContent: "center", gap: "6px", fontSize: "13px", color: confirmClear ? "#ff4d4d" : undefined }}
                            >
                                {confirmClear ? <HiExclamationTriangle style={{ fontSize: "16px" }} /> : <HiXCircle style={{ fontSize: "16px" }} />}
                                {confirmClear ? "Are you sure?" : "Clear all"}
                            </DialogButton>
                        </Focusable>
                    )}
                </div>
                <style>{`.dt-rowfocus { background: rgba(103,160,255,0.22) !important; }`}</style>
                {entries === null && <p style={{ color: "#aaa" }}>Loading...</p>}
                {entries !== null && shown.length === 0 && (
                    <p style={{ color: "#aaa" }}>{all.length === 0 ? "Nothing cached yet." : "Nothing to show."}</p>
                )}
                {shown.length > 0 && (
                    <div ref={wrapRef} style={{ position: "relative", flex: "1 1 auto", minHeight: 0, display: "flex" }}>
                        <Focusable key={`${filter}-${page}`} className="dt-cache-scroll" style={{ flex: 1, overflowY: "scroll", display: "flex", flexDirection: "column", gap: "6px", paddingRight: "12px", paddingTop: "8px", paddingBottom: "8px" }}>
                            {pageItems.map((e) => (
                                <Focusable
                                    key={`${e.sourceLang}|${e.targetLang}|${e.source}`}
                                    focusWithinClassName="dt-rowfocus"
                                    style={{ display: "flex", gap: "10px", alignItems: "center", paddingRight: "10px", background: "rgba(255,255,255,0.04)", borderRadius: "4px", scrollMargin: "8px" }}
                                >
                                    <Focusable
                                        onActivate={() => {}}
                                        noFocusRing
                                        style={{ flex: "1 1 auto", minWidth: 0, display: "flex", flexDirection: "column", gap: "2px", padding: "8px 0 8px 10px", scrollMargin: "8px" }}
                                    >
                                        <div style={{ display: "flex", justifyContent: "space-between", gap: "8px", color: "rgba(255,255,255,0.28)", fontSize: "9px" }}>
                                            <span><span style={{ fontWeight: "bold" }}>Translated with:</span> {cacheProviderLabel(e.provider)}</span>
                                            <span><span style={{ fontWeight: "bold" }}>Date:</span> {e.createdAt ? new Date(e.createdAt * 1000).toLocaleString([], { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : ""}</span>
                                            <span><span style={{ fontWeight: "bold" }}>Reused:</span> {e.hits} {e.hits === 1 ? "time" : "times"}</span>
                                        </div>
                                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                                            <span style={{ fontSize: "14px", flexShrink: 0, width: "20px", textAlign: "center" }}>{cacheLangFlag(e.sourceLang)}</span>
                                            <span style={{ color: "#dcdedf", fontSize: "11px", flex: "1 1 auto", minWidth: 0 }}>{e.source}</span>
                                        </div>
                                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                                            <span style={{ fontSize: "14px", flexShrink: 0, width: "20px", textAlign: "center" }}>{cacheLangFlag(e.targetLang)}</span>
                                            <span style={{ color: "#6fcf97", fontStyle: "italic", fontSize: "11px", flex: "1 1 auto", minWidth: 0 }}>{e.translation}</span>
                                        </div>
                                    </Focusable>
                                    <DialogButton
                                        onClick={() => removeEntry(e)}
                                        style={{ minWidth: "32px", width: "32px", height: "32px", padding: "0", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center" }}
                                    >
                                        <HiTrash />
                                    </DialogButton>
                                </Focusable>
                            ))}
                        </Focusable>
                        <div ref={trackRef} style={{ position: "absolute", top: 0, right: "2px", width: "8px", height: "100%", borderRadius: "4px", background: "rgba(255,255,255,0.08)", display: "none" }}>
                            <div ref={thumbRef} onMouseDown={onThumbDown} style={{ position: "absolute", left: 0, width: "100%", height: 0, background: "rgba(255,255,255,0.4)", borderRadius: "4px", cursor: "pointer" }} />
                        </div>
                    </div>
                )}
                {totalPages > 1 && (
                    <Focusable style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "12px", marginTop: "8px", flexShrink: 0 }}>
                        {pagerButton("Prev", page > 0, () => setPage(p => Math.max(0, p - 1)))}
                        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", minWidth: "80px" }}>
                            <span style={{ fontSize: "12px", color: "#8b929a" }}>Page {page + 1} / {totalPages}</span>
                            <span style={{ fontSize: "9px", color: "rgba(255,255,255,0.28)" }}>{pageItems.length} of {shown.length}</span>
                        </div>
                        {pagerButton("Next", page < totalPages - 1, () => setPage(p => Math.min(totalPages - 1, p + 1)))}
                    </Focusable>
                )}
            </Focusable>
        </ModalRoot>
    );
};
