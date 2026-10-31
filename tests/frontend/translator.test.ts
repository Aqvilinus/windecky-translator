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
    state.onStateChanged((visible, _image, _regions, _loading, step, _detail, isError) => {
        if (visible && step) steps.push({ step, isError });
    });
    const logic = new GameTranslatorLogic(state);
    logic.setInputLanguage('auto');
    logic.setTargetLanguage('en');
    return { logic, steps };
}

describe('GameTranslatorLogic errors', () => {
    beforeEach(() => {
        replies = {
            get_enabled_state: true,
            take_screenshot: { path: 'shot.png', base64: 'x' },
        };
    });

    it('shows why OCR failed', async () => {
        replies.recognize_text_file = { error: 'ocr_failed', message: 'On-device OCR timed out after 120 s' };
        const { logic, steps } = startTranslator();
        await logic.takeScreenshotAndTranslate();
        expect(steps.at(-1)).toEqual({ step: 'On-device OCR timed out after 120 s', isError: true });
    });

    it('still says "No text found" when the screen has no text', async () => {
        replies.recognize_text_file = [];
        const { logic, steps } = startTranslator();
        await logic.takeScreenshotAndTranslate();
        expect(steps.at(-1)).toEqual({ step: 'No text found', isError: false });
    });
});
