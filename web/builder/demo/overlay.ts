import { expect, type Browser, type BrowserContext, type BrowserContextOptions, type Locator, type Page } from '@playwright/test';
import { mkdirSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';

/**
 * Demo-only helpers for the scripted videos (`make demo-videos`, docs/demos.md): a visible
 * cursor with a click ripple and short captions, injected into the page by the test, never
 * part of an app bundle; deliberate pacing; and recording to a fixed file name.
 */

/** Where raw recordings go (the Makefile sets it; render.sh turns them into MP4 + GIF). */
export const RAW_DIR = process.env.OSP_DEMO_RAW ?? join(process.cwd(), '..', '..', '.build', 'demo', 'raw');

/**
 * The browser renders at this device scale (playwright.config.ts launches Chromium with
 * --force-device-scale-factor; the context option does not reach the screencast), so a
 * 1280 x 720 viewport records sharp 1920 x 1080 frames.
 */
export const SCALE = 1.5;

/** Pacing multiplier: OSP_DEMO_PACE=0.3 for a quick dry run of the scripts. */
const PACE = Number(process.env.OSP_DEMO_PACE ?? 1);

/**
 * Runs in every document before the app's own scripts (addInitScript). Draws the cursor and
 * ripple from real mouse events and a caption bar; caption and cursor position survive the
 * builder's full-page navigations via sessionStorage.
 */
function overlayInit() {
	const KEY = '__osp_demo';
	const read = (): { x: number; y: number; caption: string } => {
		try {
			return { x: 40, y: 40, caption: '', ...JSON.parse(sessionStorage.getItem(KEY) ?? '{}') };
		} catch {
			return { x: 40, y: 40, caption: '' };
		}
	};
	const write = (patch: Partial<{ x: number; y: number; caption: string }>) => {
		try {
			sessionStorage.setItem(KEY, JSON.stringify({ ...read(), ...patch }));
		} catch {
			/* storage blocked: the overlay still works for this page */
		}
	};
	const install = () => {
		if (document.getElementById('osp-demo-cursor')) return;
		const style = document.createElement('style');
		style.textContent = `
#osp-demo-cursor{position:fixed;left:0;top:0;width:26px;height:26px;z-index:2147483647;pointer-events:none;
 transform:translate(-3px,-2px);filter:drop-shadow(0 2px 3px rgba(0,0,0,.45));transition:opacity .2s}
.osp-demo-ripple{position:fixed;z-index:2147483646;pointer-events:none;width:44px;height:44px;margin:-22px 0 0 -22px;
 border-radius:50%;border:3px solid rgba(245,158,11,.95);background:rgba(245,158,11,.25);
 animation:osp-demo-ripple .6s ease-out forwards}
@keyframes osp-demo-ripple{from{transform:scale(.3);opacity:1}to{transform:scale(1.6);opacity:0}}
#osp-demo-caption{position:fixed;left:50%;bottom:84px;transform:translateX(-50%);z-index:2147483645;pointer-events:none;
 max-width:min(88vw,900px);padding:10px 22px;border-radius:999px;background:rgba(17,24,39,.88);color:#fff;
 font:600 19px/1.35 system-ui,-apple-system,"Segoe UI",sans-serif;text-align:center;box-shadow:0 6px 24px rgba(0,0,0,.3);
 transition:opacity .25s}
#osp-demo-caption[data-empty]{opacity:0}
@media (max-width:500px){#osp-demo-caption{font-size:15px;bottom:104px;padding:8px 16px;max-width:92vw;border-radius:14px}}`;
		document.documentElement.appendChild(style);
		const cursor = document.createElement('div');
		cursor.id = 'osp-demo-cursor';
		cursor.innerHTML =
			'<svg viewBox="0 0 24 24" width="26" height="26"><path d="M3 2l7.5 19 2.6-7.6L21 11z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
		const caption = document.createElement('div');
		caption.id = 'osp-demo-caption';
		caption.setAttribute('aria-hidden', 'true');
		cursor.setAttribute('aria-hidden', 'true');
		const s = read();
		cursor.style.left = `${s.x}px`;
		cursor.style.top = `${s.y}px`;
		caption.textContent = s.caption;
		if (!s.caption) caption.setAttribute('data-empty', '');
		document.documentElement.append(caption, cursor);
	};
	const w = window as unknown as { __ospDemoCaption?: (t: string) => void };
	w.__ospDemoCaption = (text: string) => {
		install();
		const c = document.getElementById('osp-demo-caption')!;
		c.textContent = text;
		c.toggleAttribute('data-empty', !text);
		write({ caption: text });
	};
	addEventListener(
		'mousemove',
		(e) => {
			install();
			const c = document.getElementById('osp-demo-cursor')!;
			c.style.left = `${e.clientX}px`;
			c.style.top = `${e.clientY}px`;
			write({ x: e.clientX, y: e.clientY });
		},
		true
	);
	addEventListener(
		'mousedown',
		(e) => {
			install();
			const r = document.createElement('div');
			r.className = 'osp-demo-ripple';
			r.style.left = `${e.clientX}px`;
			r.style.top = `${e.clientY}px`;
			document.documentElement.appendChild(r);
			setTimeout(() => r.remove(), 700);
		},
		true
	);
	if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install);
	else install();
}

/** Caption times per recording (seconds from its start), written next to the video for docs/demos.md. */
const log = new WeakMap<BrowserContext, { start: number; captions: { t: number; text: string }[] }>();

/** Last mouse position per page (Playwright has no getter), so moves can glide from it. */
const where = new WeakMap<Page, { x: number; y: number }>();

/** A new recording context: the overlay is installed in every page it opens. */
export async function recordingContext(browser: Browser, name: string, options: BrowserContextOptions = {}) {
	const dir = join(RAW_DIR, `.tmp-${name}`);
	rmSync(dir, { recursive: true, force: true });
	const viewport = options.viewport ?? { width: 1280, height: 720 };
	const context = await browser.newContext({
		colorScheme: 'light',
		...options,
		viewport,
		recordVideo: { dir, size: { width: Math.round(viewport.width * SCALE), height: Math.round(viewport.height * SCALE) } }
	});
	await context.addInitScript(overlayInit);
	log.set(context, { start: Date.now(), captions: [] });
	return context;
}

/** Close the context and move its (single page's) recording to RAW_DIR/<name>.webm. */
export async function saveRecording(context: BrowserContext, page: Page, name: string) {
	const video = page.video();
	await context.close();
	if (!video) throw new Error('no video recorded');
	const out = join(RAW_DIR, `${name}.webm`);
	mkdirSync(dirname(out), { recursive: true });
	rmSync(out, { force: true });
	const tmp = await video.path();
	renameSync(tmp, out);
	const l = log.get(context);
	if (l) writeFileSync(join(RAW_DIR, `${name}.captions.json`), JSON.stringify(l.captions, null, 1));
	rmSync(dirname(tmp), { recursive: true, force: true });
}

/** An intentional pause so a viewer can follow (the only fixed waits in the demos). */
export async function beat(page: Page, ms = 700) {
	await page.waitForTimeout(Math.round(ms * PACE));
}

/** Show a caption (empty string hides it) and give the viewer time to read it. */
export async function caption(page: Page, text: string, ms = 1400) {
	await page.evaluate((t) => (window as unknown as { __ospDemoCaption?: (t: string) => void }).__ospDemoCaption?.(t), text);
	const l = log.get(page.context());
	if (l && text) l.captions.push({ t: Math.round((Date.now() - l.start) / 100) / 10, text });
	await beat(page, ms);
}

/** Glide the mouse to the middle of `target` (scrolling it into view first). */
export async function moveTo(page: Page, target: Locator) {
	await target.scrollIntoViewIfNeeded();
	await expect(target).toBeVisible();
	const box = (await target.boundingBox())!;
	const to = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
	const from = where.get(page) ?? { x: to.x - 120, y: to.y - 80 };
	const steps = Math.max(8, Math.min(40, Math.round(Math.hypot(to.x - from.x, to.y - from.y) / 25)));
	await page.mouse.move(to.x, to.y, { steps: Math.max(2, Math.round(steps * Math.min(PACE, 1))) });
	where.set(page, to);
	await beat(page, 220);
}

/** Move the visible cursor to `target`, then click it. */
export async function click(page: Page, target: Locator) {
	await moveTo(page, target);
	await target.click();
	await beat(page, 380);
}

/** Click a field, clear it and type `text` at a readable speed. */
export async function type(page: Page, field: Locator, text: string, opts: { clear?: boolean } = {}) {
	await click(page, field);
	if (opts.clear !== false) {
		await page.keyboard.press('ControlOrMeta+a');
		await page.keyboard.press('Backspace');
	}
	await expect(field).toBeFocused();
	await page.keyboard.type(text, { delay: Math.round(38 * PACE) });
	await beat(page, 350);
}

/** Press a key (or chord) with a short pause after, so the result is visible. */
export async function press(page: Page, key: string) {
	await page.keyboard.press(key);
	await beat(page, 450);
}

/** Remember where the mouse is after a navigation (the overlay restores it on load). */
export function resetCursor(page: Page, x: number, y: number) {
	where.set(page, { x, y });
}
