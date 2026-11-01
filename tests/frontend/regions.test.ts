// src/regions.ts: OCR boxes merged into lines and paragraphs, and what is not worth translating dropped.
import { describe, expect, it } from 'vitest';

import { filterUntranslatable, mergeRegions } from '../../src/regions';

const box = (text: string, left: number, top: number, width: number, height = 20) =>
    ({ text, rect: { left, top, right: left + width, bottom: top + height } });

describe('mergeRegions', () => {
    it('glues the words of one line', () => {
        const [line] = mergeRegions([box('Press', 100, 100, 50), box('start', 156, 100, 50)]);
        expect(line.text).toBe('Press start');
        expect(line.rect).toEqual({ left: 100, top: 100, right: 206, bottom: 120 });
    });

    it('glues the lines of one paragraph', () => {
        const regions = mergeRegions([
            box('The bridge is out.', 100, 100, 180), box('Take the north road.', 100, 124, 190),
        ]);
        expect(regions).toHaveLength(1);
        expect(regions[0].text).toContain('The bridge is out.');
        expect(regions[0].text).toContain('Take the north road.');
    });

    it('keeps labels far apart separate, in reading order', () => {
        const regions = mergeRegions([box('Options', 900, 600, 80), box('New game', 100, 100, 90)]);
        expect(regions.map(r => r.text)).toEqual(['New game', 'Options']);
    });
});

describe('filterUntranslatable', () => {
    const kept = (...texts: string[]) => filterUntranslatable(texts.map(t => box(t, 0, 0, 50))).map(r => r.text);

    it('drops numbers, counters and stats', () => {
        expect(kept('1250', '12/20', 'x3', 'LVL 5', 'HP 40', '45%', '12:30 PM', '---')).toEqual([]);
    });

    it('keeps words, short common ones and CJK', () => {
        expect(kept('Continue', 'OK', 'はい', 'Load game')).toEqual(['Continue', 'OK', 'はい', 'Load game']);
    });
});
