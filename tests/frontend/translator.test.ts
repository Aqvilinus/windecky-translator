// src/Translator.tsx: a failure in the pipeline is shown on the overlay with its reason, never as "No text found".
import { beforeEach, describe, expect, it, vi } from 'vitest';

let replies: Record<string, unknown> = {};

vi.mock('@decky/api', () => ({
    call: vi.fn((method: string) => Promise.resolve(replies[method])),
    toaster: { toast: vi.fn() },
}));
vi.mock('@decky/ui', () => ({ Router: { MainRunningApp: { display_name: 'Game' } } }));

const { GameTranslatorLogic } = await import('../../src/Translator');
const { ImageState } = await import('../../src/Overlay');

function startTranslator() {
    const state = new ImageState();
    const steps: Array<{ step: string; isError: boolean }> = [];
    state.subscribe(s => {
        if (s.visible && s.processingStep) steps.push({ step: s.processingStep, isError: s.processingIsError });
    });
    const logic = new GameTranslatorLogic(state);
    logic.setInputLanguage('auto');
    logic.setTargetLanguage('en');
    return { logic, steps };
}

describe('GameTranslatorLogic errors', () => {
    beforeEach(() => {
        replies = {
            take_screenshot: { path: 'shot.png' },
        };
    });

    it('shows why OCR failed', async () => {
        replies.recognize_text_file = { error: 'ocr_failed', message: 'On-device OCR timed out after 120 s' };
        const { logic, steps } = startTranslator();
        await logic.takeScreenshotAndTranslate();
        expect(steps.at(-1)).toEqual({ step: 'On-device OCR timed out after 120 s', isError: true });
    });

    it('shows why translation failed', async () => {
        replies.recognize_text_file = [{ text: 'Neues Spiel', rect: { left: 0, top: 0, right: 90, bottom: 20 }, confidence: 1 }];
        replies.translate_text = { error: 'translation_failed', message: 'The translation service did not answer' };
        const { logic, steps } = startTranslator();
        await logic.takeScreenshotAndTranslate();
        expect(steps.at(-1)).toEqual({ step: 'The translation service did not answer', isError: true });
    });

    it('still says "No text found" when the screen has no text', async () => {
        replies.recognize_text_file = [];
        const { logic, steps } = startTranslator();
        await logic.takeScreenshotAndTranslate();
        expect(steps.at(-1)).toEqual({ step: 'No text found', isError: false });
    });
});

describe('ImageState', () => {
    it('sends the changes made in one go once', async () => {
        const state = new ImageState();
        const sent: boolean[] = [];
        state.subscribe(s => sent.push(s.visible));
        state.startLoading('Recognizing');
        state.updateProcessingStep('Recognizing', false, 'On-Device');
        await Promise.resolve();
        expect(sent).toEqual([true]);
        state.hide();
        await Promise.resolve();
        expect(sent).toEqual([true, false]);
    });
});
