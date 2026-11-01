// src/translator.ts: a failure in the pipeline is shown on the overlay with its reason, never as "No text found".
import { beforeEach, describe, expect, it, vi } from 'vitest';

let replies: Record<string, unknown> = {};

vi.mock('@decky/api', () => ({
    // each backend method answers from replies, by its name in main.py
    callable: (method: string) => vi.fn(() => Promise.resolve(replies[method])),
    toaster: { toast: vi.fn() },
}));

const { Translator } = await import('../../src/translator');
const { OverlayStore } = await import('../../src/overlay');

function startTranslator() {
    const state = new OverlayStore();
    const steps: Array<{ step: string; isError: boolean }> = [];
    state.subscribe(s => {
        if (s.visible && s.status) steps.push({ step: s.status, isError: s.isError });
    });
    const translator = new Translator(state);
    translator.applySettings({
        enabled: true, inputLanguage: 'auto', targetLanguage: 'en', ocrProvider: 'chromescreenai',
        translationProvider: 'freegoogle', googleApiKey: '', geminiApiKey: '', debugMode: false, fontScale: 1,
    });
    return { translator, steps };
}

describe('Translator errors', () => {
    beforeEach(() => {
        replies = {
            capture_screen: { id: 1 },
        };
    });

    it('shows why OCR failed', async () => {
        replies.recognize_capture = { error: 'ocr_failed', message: 'On-device OCR timed out after 120 s' };
        const { translator, steps } = startTranslator();
        await translator.translateScreen();
        expect(steps.at(-1)).toEqual({ step: 'On-device OCR timed out after 120 s', isError: true });
    });

    it('shows why translation failed', async () => {
        replies.recognize_capture = [{ text: 'Neues Spiel', rect: { left: 0, top: 0, right: 90, bottom: 20 } }];
        replies.translate_text = { error: 'translation_failed', message: 'The translation service did not answer' };
        const { translator, steps } = startTranslator();
        await translator.translateScreen();
        expect(steps.at(-1)).toEqual({ step: 'The translation service did not answer', isError: true });
    });

    it('still says "No text found" when the screen has no text', async () => {
        replies.recognize_capture = [];
        const { translator, steps } = startTranslator();
        await translator.translateScreen();
        expect(steps.at(-1)).toEqual({ step: 'No text found', isError: false });
    });
});

describe('OverlayStore', () => {
    it('sends the changes made in one go once', async () => {
        const state = new OverlayStore();
        const sent: boolean[] = [];
        state.subscribe(s => sent.push(s.visible));
        state.showLoading('Recognizing');
        state.setStatus('Recognizing', false, 'On-Device');
        await Promise.resolve();
        expect(sent).toEqual([true]);
        state.hide();
        await Promise.resolve();
        expect(sent).toEqual([true, false]);
    });
});
