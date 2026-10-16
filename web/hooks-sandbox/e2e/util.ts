/** Shared Playwright helpers for the hooks adversarial gate. */

import { expect, type APIRequestContext, type Frame, type Page } from '@playwright/test';

export interface Hit {
	server: string;
	kind: string;
	method: string;
	url: string;
	origin: string | null;
}

export async function resetEgress(request: APIRequestContext): Promise<void> {
	await request.post('/__reset');
}

export async function egressLog(request: APIRequestContext): Promise<Hit[]> {
	return (await (await request.get('/__log')).json()) as Hit[];
}

/** Open the embedding page and return the runtime frame (where `window.H` lives). */
export async function openRuntime(page: Page): Promise<Frame> {
	const errors: string[] = [];
	page.on('pageerror', (e) => errors.push(String(e)));
	await page.goto('/index.html');
	const frame = page.frame({ url: /runtime\.html$/ });
	expect(frame, 'runtime frame').toBeTruthy();
	await frame!.waitForFunction(() => document.documentElement.dataset.ready === 'yes');
	return frame!;
}

/** The main thread stays responsive: a timer fires on time. */
export async function responsive(frame: Frame): Promise<number> {
	return frame.evaluate(async () => {
		const t0 = performance.now();
		await new Promise((r) => setTimeout(r, 20));
		return performance.now() - t0;
	});
}
