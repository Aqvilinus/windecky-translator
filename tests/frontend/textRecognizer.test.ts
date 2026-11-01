// src/TextRecognizer.tsx: OCR boxes glued into lines and paragraphs, and what is not worth translating dropped.
import { describe, expect, it, vi } from 'vitest';

vi.mock('@decky/api', () => ({ callable: () => vi.fn() }));

const { TextRecognizer } = await import('../../src/TextRecognizer');

const box = (text: string, left: number, top: number, width: number, height = 20, confidence = 1) =>
    ({ text, rect: { left, top, right: left + width, bottom: top + height }, isDialog: false, confidence });

describe('applyAutoGlue', () => {
    const recognizer = new TextRecognizer();

    it('glues the words of one line', () => {
        const [line] = recognizer.applyAutoGlue([box('Press', 100, 100, 50), box('start', 156, 100, 50)]);
        expect(line.text).toBe('Press start');
        expect(line.rect).toEqual({ left: 100, top: 100, right: 206, bottom: 120 });
    });

    it('glues the lines of one paragraph', () => {
        const regions = recognizer.applyAutoGlue([
            box('The bridge is out.', 100, 100, 180), box('Take the north road.', 100, 124, 190),
        ]);
        expect(regions).toHaveLength(1);
        expect(regions[0].text).toContain('The bridge is out.');
        expect(regions[0].text).toContain('Take the north road.');
    });

    it('keeps labels far apart separate, in reading order', () => {
        const regions = recognizer.applyAutoGlue([box('Options', 900, 600, 80), box('New game', 100, 100, 90)]);
        expect(regions.map(r => r.text)).toEqual(['New game', 'Options']);
    });
});

describe('filterUntranslatableText', () => {
    const recognizer = new TextRecognizer();
    const kept = (...texts: string[]) => recognizer.filterUntranslatableText(texts.map(t => box(t, 0, 0, 50))).map(r => r.text);

    it('drops numbers, counters and stats', () => {
        expect(kept('1250', '12/20', 'x3', 'LVL 5', 'HP 40', '45%', '12:30 PM', '---')).toEqual([]);
    });

    it('keeps words, short common ones and CJK', () => {
        expect(kept('Continue', 'OK', 'はい', 'Load game')).toEqual(['Continue', 'OK', 'はい', 'Load game']);
    });

    it('drops lines below the confidence threshold', () => {
        recognizer.setConfidenceThreshold(0.6);
        expect(recognizer.filterUntranslatableText([box('Blurry', 0, 0, 50, 20, 0.4)])).toEqual([]);
    });
});
