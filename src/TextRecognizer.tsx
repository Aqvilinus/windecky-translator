import { backend } from "./backend";
import { logger } from "./Logger";
import { throwIfBackendError } from "./errors";

export interface TextRegion {
    text: string;
    rect: {
        left: number;
        top: number;
        right: number;
        bottom: number;
    };
    confidence?: number;
    textColor?: string;
    fontSize?: number;
    textDensity?: number;
    textContext?: string;
    lineNumber?: number;
    indent?: number;
    typographyType?: string;
    alignment?: string;
    translatedText?: string;  // from an OCR provider that also translates (Gemini Vision)
}

// Transitive merging: if A merges with B and B with C, all three end up in one group whatever the check order.
class UnionFind {
    private parent: number[];
    private rank: number[];

    constructor(n: number) {
        this.parent = Array.from({ length: n }, (_, i) => i);
        this.rank = new Array(n).fill(0);
    }

    find(x: number): number {
        while (this.parent[x] !== x) {
            this.parent[x] = this.parent[this.parent[x]];
            x = this.parent[x];
        }
        return x;
    }

    union(x: number, y: number): void {
        const px = this.find(x), py = this.find(y);
        if (px === py) return;
        if (this.rank[px] < this.rank[py]) {
            this.parent[px] = py;
        } else if (this.rank[px] > this.rank[py]) {
            this.parent[py] = px;
        } else {
            this.parent[py] = px;
            this.rank[px]++;
        }
    }

    getGroups(): Map<number, number[]> {
        const groups = new Map<number, number[]>();
        for (let i = 0; i < this.parent.length; i++) {
            const root = this.find(i);
            if (!groups.has(root)) groups.set(root, []);
            groups.get(root)!.push(i);
        }
        return groups;
    }
}

function computeMedianHeight(regions: TextRegion[]): number {
    const heights = regions
        .map(r => r.rect.bottom - r.rect.top)
        .filter(h => h > 0)
        .sort((a, b) => a - b);

    if (heights.length === 0) return 20;
    return heights[Math.floor(heights.length / 2)];
}

// How readily lines are glued into paragraphs (0.25 normal .. 1.0 huge): scales the vertical gap threshold
const GROUPING_POWER = 0.25;

const SEPARATOR_LINE = /^[-=_*~.]{3,}$/;
const STARTS_WITH_CLOSING_PUNCTUATION = /^[.,!?:;)\]"'。、）」』】〉》)]/;
const ENDS_WITH_OPENING_PUNCTUATION = /[(\["'（「『【〈《(]\s*$/;
const MIN_REGION_SIZE_PX = 5;

export class TextRecognizer {
    private confidenceThreshold: number = 0.6;

    constructor() {
        logger.info('TextRecognizer', 'TextRecognizer initialized');
    }

    setConfidenceThreshold(threshold: number): void {
        this.confidenceThreshold = threshold;
    }

    // Thresholds here and in assembleParagraphs are multiples of the median line height, never absolute pixels.
    private assembleLines(regions: TextRegion[], medianH: number): TextRegion[] {
        const n = regions.length;
        if (n <= 1) return [...regions];

        const uf = new UnionFind(n);

        const indexed = regions.map((r, i) => ({ r, i }));
        indexed.sort((a, b) => a.r.rect.top - b.r.rect.top);

        for (let a = 0; a < n; a++) {
            for (let b = a + 1; b < n; b++) {
                const ra = indexed[a].r, rb = indexed[b].r;

                // sorted by top edge: every box after b is even lower
                if (rb.rect.top - ra.rect.bottom > medianH) break;

                const yCenterA = (ra.rect.top + ra.rect.bottom) / 2;
                const yCenterB = (rb.rect.top + rb.rect.bottom) / 2;
                if (Math.abs(yCenterA - yCenterB) > 0.5 * medianH) continue;

                const hA = ra.rect.bottom - ra.rect.top;
                const hB = rb.rect.bottom - rb.rect.top;
                if (hA > 0 && hB > 0 && Math.max(hA, hB) / Math.min(hA, hB) > 1.5) continue;

                // negative when the boxes overlap
                const gap = Math.max(ra.rect.left, rb.rect.left) - Math.min(ra.rect.right, rb.rect.right);
                if (gap > 1.0 * medianH) continue;

                uf.union(indexed[a].i, indexed[b].i);
            }
        }

        const groups = Array.from(uf.getGroups().values());
        return this.extractMergedRegions(groups, regions, "horizontal", medianH);
    }

    private assembleParagraphs(lines: TextRegion[], medianH: number): TextRegion[] {
        const n = lines.length;
        if (n <= 1) return [...lines];

        const power = GROUPING_POWER;
        const uf = new UnionFind(n);

        const indexed = lines.map((l, i) => ({ l, i }));
        indexed.sort((a, b) => a.l.rect.top - b.l.rect.top);

        for (let a = 0; a < n; a++) {
            for (let b = a + 1; b < n; b++) {
                const la = indexed[a].l, lb = indexed[b].l;

                if (lb.rect.top - la.rect.bottom > 3.0 * medianH * power) break;

                const vertGap = Math.max(0, lb.rect.top - la.rect.bottom);
                if (vertGap > 1.5 * medianH * power) continue;

                const overlapLeft = Math.max(la.rect.left, lb.rect.left);
                const overlapRight = Math.min(la.rect.right, lb.rect.right);
                const overlapWidth = Math.max(0, overlapRight - overlapLeft);
                const widthA = la.rect.right - la.rect.left;
                const widthB = lb.rect.right - lb.rect.left;
                const minWidth = Math.min(widthA, widthB);

                if (minWidth > 0 && overlapWidth / minWidth < 0.3) continue;

                // compare font sizes per line: OCR may return one box for several visual lines
                const hA = la.rect.bottom - la.rect.top;
                const hB = lb.rect.bottom - lb.rect.top;
                const estLinesA = Math.max(1, Math.round(hA / medianH));
                const estLinesB = Math.max(1, Math.round(hB / medianH));
                const lineHA = hA / estLinesA;
                const lineHB = hB / estLinesB;
                if (lineHA > 0 && lineHB > 0 && Math.max(lineHA, lineHB) / Math.min(lineHA, lineHB) > 1.4) continue;

                // left-, right- or center-aligned lines merge; lines aligned no way at all are separate UI elements
                const leftEdgeDist = Math.abs(la.rect.left - lb.rect.left);
                const rightEdgeDist = Math.abs(la.rect.right - lb.rect.right);
                const centerA = (la.rect.left + la.rect.right) / 2;
                const centerB = (lb.rect.left + lb.rect.right) / 2;
                const centerDist = Math.abs(centerA - centerB);
                const edgeThresh = 2.0 * medianH;
                const centerThresh = 1.0 * medianH;
                if (leftEdgeDist > edgeThresh && rightEdgeDist > edgeThresh && centerDist > centerThresh) continue;

                // a very narrow line above a wide one is a stray label; below it, it can be a paragraph's last line
                const maxWidth = Math.max(widthA, widthB);
                if (maxWidth > 0) {
                    const widthRatio = minWidth / maxWidth;
                    const narrowIsUpper = (widthA < widthB && la.rect.top < lb.rect.top) ||
                                          (widthB < widthA && lb.rect.top < la.rect.top);
                    if (widthRatio < 0.15 && narrowIsUpper) continue;
                }

                uf.union(indexed[a].i, indexed[b].i);
            }
        }

        const groups = Array.from(uf.getGroups().values());
        const refined = this.splitOvermerged(groups, lines, medianH);
        logger.debug('TextRecognizer', `Auto-glue: Split pass refined ${groups.length} groups into ${refined.length} groups`);
        return this.extractMergedRegions(refined, lines, "vertical", medianH);
    }

    private splitOvermerged(groups: number[][], lines: TextRegion[], medianH: number): number[][] {
        const result: number[][] = [];

        for (const group of groups) {
            // at most one gap: nothing to compare it with
            if (group.length <= 2) {
                result.push(group);
                continue;
            }

            const sorted = [...group].sort((a, b) => {
                const yA = (lines[a].rect.top + lines[a].rect.bottom) / 2;
                const yB = (lines[b].rect.top + lines[b].rect.bottom) / 2;
                return yA - yB;
            });

            const gaps: number[] = [];
            for (let i = 0; i < sorted.length - 1; i++) {
                gaps.push(Math.max(0, lines[sorted[i + 1]].rect.top - lines[sorted[i]].rect.bottom));
            }

            const sortedGaps = [...gaps].sort((a, b) => a - b);
            const medianGap = sortedGaps[Math.floor(sortedGaps.length / 2)];

            const splitAfter = new Set<number>();

            for (let i = 0; i < gaps.length; i++) {
                // much wider than the group's usual gap, and too wide to be bounding box jitter
                if (medianGap > 0 && gaps[i] > 2.5 * medianGap && gaps[i] > 0.8 * medianH) {
                    splitAfter.add(i);
                }
                // When lines nearly overlap (medianGap ~ 0), any real gap stands out
                if (medianGap <= 1 && gaps[i] > 1.2 * medianH) {
                    splitAfter.add(i);
                }

                const text = lines[sorted[i]].text.trim();
                if (SEPARATOR_LINE.test(text)) {
                    if (i > 0) splitAfter.add(i - 1);
                    splitAfter.add(i);
                }
                if (i + 1 < sorted.length) {
                    const nextText = lines[sorted[i + 1]].text.trim();
                    if (SEPARATOR_LINE.test(nextText)) {
                        splitAfter.add(i);
                    }
                }
            }

            if (splitAfter.size === 0) {
                result.push(sorted);
                continue;
            }

            let subGroup: number[] = [];
            for (let i = 0; i < sorted.length; i++) {
                subGroup.push(sorted[i]);
                if (splitAfter.has(i)) {
                    if (subGroup.length > 0) result.push(subGroup);
                    subGroup = [];
                }
            }
            if (subGroup.length > 0) result.push(subGroup);
        }

        return result;
    }

    private extractMergedRegions(
        groups: number[][],
        regions: TextRegion[],
        direction: "horizontal" | "vertical",
        medianH: number
    ): TextRegion[] {
        const merged: TextRegion[] = [];

        for (const indices of groups) {
            if (indices.length === 1) {
                merged.push({ ...regions[indices[0]] });
                continue;
            }

            const sorted = indices
                .map(i => regions[i])
                .sort((a, b) => {
                    if (direction === "horizontal") return a.rect.left - b.rect.left;
                    const yCenterA = (a.rect.top + a.rect.bottom) / 2;
                    const yCenterB = (b.rect.top + b.rect.bottom) / 2;
                    return yCenterA - yCenterB;
                });

            let combinedText = sorted[0].text;
            let combinedTranslatedText = sorted[0].translatedText ?? null;
            let combinedRect = { ...sorted[0].rect };
            let confidenceSum = sorted[0].confidence ?? 0;
            let confidenceCount = sorted[0].confidence !== undefined ? 1 : 0;

            for (let i = 1; i < sorted.length; i++) {
                const region = sorted[i];
                const separator = direction === "horizontal"
                    ? this.getHorizontalSpacing(sorted[i - 1], region, medianH)
                    : "\n";

                combinedText += separator + region.text;
                if (combinedTranslatedText !== null && region.translatedText) {
                    combinedTranslatedText += separator + region.translatedText;
                }

                combinedRect = {
                    left: Math.min(combinedRect.left, region.rect.left),
                    top: Math.min(combinedRect.top, region.rect.top),
                    right: Math.max(combinedRect.right, region.rect.right),
                    bottom: Math.max(combinedRect.bottom, region.rect.bottom),
                };

                if (region.confidence !== undefined) {
                    confidenceSum += region.confidence;
                    confidenceCount++;
                }
            }

            const result: TextRegion = {
                text: combinedText,
                rect: combinedRect,
            };
            if (combinedTranslatedText !== null) {
                result.translatedText = combinedTranslatedText;
            }
            if (confidenceCount > 0) {
                result.confidence = confidenceSum / confidenceCount;
            }
            merged.push(result);
        }

        return merged;
    }

    private getHorizontalSpacing(a: TextRegion, b: TextRegion, _medianH: number): string {
        if (STARTS_WITH_CLOSING_PUNCTUATION.test(b.text)) {
            return "";
        }
        if (ENDS_WITH_OPENING_PUNCTUATION.test(a.text)) {
            return "";
        }

        const cjkPattern = /[\u3000-\u9FFF\uAC00-\uD7AF\uF900-\uFAFF\uFF00-\uFFEF]/;
        if (cjkPattern.test(a.text.slice(-1)) || cjkPattern.test(b.text.charAt(0))) {
            return "";
        }

        return " ";
    }

    // A merged paragraph's rect (the union of its lines) can reach into its neighbours. Of two overlapping regions
    // the smaller is dropped when mostly inside the other, otherwise trimmed at the edge that loses the least area.
    private resolveOverlaps(regions: TextRegion[]): TextRegion[] {
        if (regions.length <= 1) return regions;

        // copies: their rects get trimmed
        const result = regions.map(r => ({ ...r, rect: { ...r.rect } }));

        // larger (merged) regions first: they win
        const byArea = result
            .map((r, i) => ({ i, area: (r.rect.right - r.rect.left) * (r.rect.bottom - r.rect.top) }))
            .sort((a, b) => b.area - a.area);

        const removed = new Set<number>();

        for (let ai = 0; ai < byArea.length; ai++) {
            const idxA = byArea[ai].i;
            if (removed.has(idxA)) continue;
            const a = result[idxA].rect;

            for (let bi = ai + 1; bi < byArea.length; bi++) {
                const idxB = byArea[bi].i;
                if (removed.has(idxB)) continue;
                const b = result[idxB].rect;

                const oLeft = Math.max(a.left, b.left);
                const oTop = Math.max(a.top, b.top);
                const oRight = Math.min(a.right, b.right);
                const oBottom = Math.min(a.bottom, b.bottom);

                if (oLeft >= oRight || oTop >= oBottom) continue;

                const overlapArea = (oRight - oLeft) * (oBottom - oTop);
                const bArea = (b.right - b.left) * (b.bottom - b.top);

                if (bArea > 0 && overlapArea / bArea > 0.5) {
                    removed.add(idxB);
                    continue;
                }

                const bW = b.right - b.left;
                const bH = b.bottom - b.top;
                const oW = oRight - oLeft;
                const oH = oBottom - oTop;

                // b's area each trim loses, for the edges the overlap is on
                const candidates: { edge: string; loss: number }[] = [];

                if (oLeft === b.left || oLeft - b.left < oW) {
                    candidates.push({ edge: 'left', loss: oW * bH });
                }
                if (oRight === b.right || b.right - oRight < oW) {
                    candidates.push({ edge: 'right', loss: oW * bH });
                }
                if (oTop === b.top || oTop - b.top < oH) {
                    candidates.push({ edge: 'top', loss: bW * oH });
                }
                if (oBottom === b.bottom || b.bottom - oBottom < oH) {
                    candidates.push({ edge: 'bottom', loss: bW * oH });
                }

                if (candidates.length === 0) {
                    removed.add(idxB);
                    continue;
                }

                candidates.sort((x, y) => x.loss - y.loss);
                switch (candidates[0].edge) {
                    case 'left': b.left = oRight; break;
                    case 'right': b.right = oLeft; break;
                    case 'top': b.top = oBottom; break;
                    case 'bottom': b.bottom = oTop; break;
                }

                if (b.right - b.left < MIN_REGION_SIZE_PX || b.bottom - b.top < MIN_REGION_SIZE_PX) {
                    removed.add(idxB);
                }
            }
        }

        return result.filter((_, i) => !removed.has(i));
    }

    applyAutoGlue(regions: TextRegion[]): TextRegion[] {
        if (!regions || regions.length <= 1) return regions;

        logger.debug('TextRecognizer', `Auto-glue: Processing ${regions.length} regions`);

        const medianH = computeMedianHeight(regions);
        logger.debug('TextRecognizer', `Auto-glue: Median line height = ${medianH}px`);

        const lines = this.assembleLines(regions, medianH);
        logger.debug('TextRecognizer', `Auto-glue: Phase 1 produced ${lines.length} lines from ${regions.length} boxes`);

        const paragraphs = this.assembleParagraphs(lines, medianH);
        logger.debug('TextRecognizer', `Auto-glue: Phase 2 produced ${paragraphs.length} paragraphs from ${lines.length} lines`);

        // reading order: rows top to bottom, each row left to right
        paragraphs.sort((a, b) => {
            const yCenterA = (a.rect.top + a.rect.bottom) / 2;
            const yCenterB = (b.rect.top + b.rect.bottom) / 2;
            if (Math.abs(yCenterA - yCenterB) < 0.3 * medianH) {
                return a.rect.left - b.rect.left;
            }
            return yCenterA - yCenterB;
        });

        const resolved = this.resolveOverlaps(paragraphs);
        if (resolved.length !== paragraphs.length) {
            logger.debug('TextRecognizer', `Auto-glue: Overlap resolution reduced ${paragraphs.length} to ${resolved.length} regions`);
        }
        return resolved;
    }

    filterUntranslatableText(regions: TextRegion[]): TextRegion[] {
        if (!regions || regions.length === 0) return regions;

        logger.debug('TextRecognizer', `Filtering untranslatable text from ${regions.length} regions`);

        return regions.filter(region => {
            const text = region.text.trim();

            if (!text) return false;

            if (region.confidence !== undefined && region.confidence < this.confidenceThreshold) {
                return false;
            }

            if (text.length === 1) return false;

            // Numeric patterns
            if (
                /^\d+$/.test(text) ||
                /^[\d\/]+$/.test(text) ||
                /^[\d\s]+$/.test(text) ||
                /^[\d\s\+\-\*\/\=\(\)]+$/.test(text) ||
                /^[\d\s,\.:\/\-]+$/.test(text) ||
                /^[+-]?\s*\d+\s*%$/.test(text) ||
                /^\d{1,2}:\d{1,2}(:\d{1,2})?\s*(AM|PM|am|pm|a\.m\.|p\.m\.)?$/.test(text) ||
                /^([WDL]\d+\s*)+$|^\d+[\-:]\d+$/.test(text)
            ) {
                return false;
            }

            // Punctuation-only
            if (/^[^\p{L}\p{N}\s]+$/u.test(text) || /^[_\-\+\*\/\=\.,;:!?@#$%^&*()[\]{}|<>~`"']+$/.test(text)) {
                return false;
            }

            // Decorative separators
            if (/^[-=_*]{3,}$/.test(text) || /^[~\u2022]{3,}$/.test(text)) {
                return false;
            }

            // Very short non-words (Latin only -- CJK carries more meaning per character)
            const hasNonLatinLetter = /[^\x00-\x7F]/.test(text) && /\p{L}/u.test(text);
            if (text.length <= 3 && !hasNonLatinLetter && !/^(OK|GO|NO|YES|ON|OFF|NEW|ADD|ALL|BUY|THE|AND|FOR|TO|IN|IS|IT|BE|BY)$/i.test(text)) {
                return false;
            }

            // File extensions
            if (/^\.[a-zA-Z0-9]{2,4}$/.test(text)) return false;

            // Social media tags
            if (/^[@#][a-zA-Z0-9_]+$/.test(text)) return false;

            // URLs and emails
            if (/^(https?:\/\/|www\.|[\w.-]+@)/.test(text)) return false;

            // Game UI patterns
            if (
                /^[xX\u00D7]\d+$|^\d+[xX\u00D7]$/.test(text) ||
                /^\d+\s*\/\s*\d+$|^\d+\s+of\s+\d+$/i.test(text) ||
                /^(LVL|LEVEL)\s*\d+$/i.test(text) ||
                /^(HP|MP|SP|AP)\s*\d+$/i.test(text) ||
                /^(STR|DEX|INT|WIS|CHA|CON|AGI)\s*\d+$/i.test(text)
            ) {
                return false;
            }

            return true;
        });
    }

    async recognizeCapture(captureId: number): Promise<TextRegion[]> {
        const regions = throwIfBackendError(await backend.recognizeCapture(captureId)) || [];
        logger.info('TextRecognizer', `Got ${regions.length} regions from OCR`);

        const mergedRegions = this.applyAutoGlue(regions);
        const filteredRegions = this.filterUntranslatableText(mergedRegions);
        logger.info('TextRecognizer', `After filtering, ${filteredRegions.length} regions remain`);

        return filteredRegions;
    }
}
