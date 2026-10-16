/**
 * Data exports through declared channels only: redirects from declared templates with
 * declared placeholders, parent messages of declared types with typed payloads to the
 * declared origin. Hook-set text is escaped and cannot reach consent or platform UI.
 */

import { expect, test } from '@playwright/test';
import { egressLog, openRuntime, resetEgress } from './util.ts';

test.beforeEach(async ({ request }) => resetEgress(request));
test.afterEach(async ({ request }) => {
	expect(await egressLog(request)).toEqual([]);
});

test('setEndRedirect with undeclared params, templates or free URLs is refused', async ({ page }) => {
	const frame = await openRuntime(page);
	const r = await frame.evaluate(async () => {
		const src = `osp.on('onBeforeSubmit', function (ctx, data, act) {
			act.setEndRedirect('prolific', { code: 'ABCD12', returnTo: 'https://evil.example' }); // extra param
			act.setEndRedirect('prolific', { code: 'AB/../../evil' });                            // fails the pattern
			act.setEndRedirect('https://evil.example/{code}', { code: 'ABCD12' });               // free-form URL
			act.setEndRedirect('constructor', {});                                                 // prototype key
		});
		osp.on('onSubmitted', function (ctx, data, act) { act.setEndRedirect('prolific', { code: 'GOOD42' }); });`;
		const { runner } = window.H.make(src);
		await runner.begin();
		await runner.next();
		await runner.next();
		await runner.next();
		const refused = window.H.hookEvents(runner.state).find((e) => e.effect.event === 'onBeforeSubmit')!.value as { diagnostics: string[] };
		const afterRefused = runner.redirectUrl();
		await runner.submitted();
		return { diagnostics: refused.diagnostics, afterRefused, url: runner.redirectUrl() };
	});
	expect(r.diagnostics).toEqual([
		'setEndRedirect:undeclared:prolific',
		'setEndRedirect:rate',
		'setEndRedirect:rate',
		'setEndRedirect:rate'
	]);
	expect(r.afterRefused).toBeNull();
	expect(r.url).toBe('https://app.prolific.com/submissions/complete?cc=GOOD42');
});

test('setEndRedirect: each refused shape on its own', async ({ page }) => {
	const frame = await openRuntime(page);
	const r = await frame.evaluate(async () => {
		const tries: Array<[string, Record<string, string>]> = [
			['prolific', { code: 'ABCD12', returnTo: 'https://evil.example' }],
			['prolific', { code: 'AB/../../evil' }],
			['https://evil.example/{code}', { code: 'ABCD12' }],
			['constructor', {}],
			['prolific', {}]
		];
		const out: string[][] = [];
		for (const [t, p] of tries) {
			const src = `osp.on('onBeforeSubmit', function (ctx, data, act) { act.setEndRedirect(${JSON.stringify(t)}, ${JSON.stringify(p)}); });`;
			const { runner, host } = window.H.make(src);
			await runner.next();
			await runner.next();
			await runner.next();
			out.push((window.H.hookEvents(runner.state).at(-1)!.value as { diagnostics: string[] }).diagnostics);
			host.dispose();
		}
		return out;
	});
	expect(r).toEqual([
		['setEndRedirect:undeclared:prolific'],
		['setEndRedirect:undeclared:prolific'],
		['setEndRedirect:undeclared:https://evil.example/{code}'],
		['setEndRedirect:undeclared:constructor'],
		['setEndRedirect:undeclared:prolific']
	]);
});

test('postToParent: undeclared types and off-schema payloads never reach the parent; declared ones go to its origin only', async ({ page }) => {
	const frame = await openRuntime(page);
	await frame.evaluate(async () => {
		const src = `osp.on('onPageShown', function (ctx, data, act) {
			act.postToParent('answers', { q1: 5 });                   // undeclared type
			act.postToParent('progress', { page: 1, email: 'x@y' });  // extra field
			act.postToParent('progress', { page: '<script>' });       // wrong type
			act.postToParent('progress', { page: 1 });                // fine
		});`;
		const { runner } = window.H.make(src);
		await runner.begin();
		// Changed code without the owner re-confirming exports: nothing at all is sent.
		const changed = window.H.make(`${src}\n// edited`, { manifest: { exportsConfirmedFor: 'sha256:old' } });
		await changed.runner.begin();
		await window.H.sleep(100);
	});
	const received = await page.evaluate(() => window.received);
	expect(received).toEqual([{ origin: 'http://127.0.0.1:4417', data: { source: 'osp-hooks', type: 'progress', payload: { page: 1 } } }]);

	// A declared parent origin that is not the actual parent: the browser drops the message.
	await page.evaluate(() => (window.received = []));
	await frame.evaluate(async () => {
		const { runner } = window.H.make(`osp.on('onPageShown', function (ctx, data, act) { act.postToParent('progress', { page: 2 }); });`, {
			parentOrigin: 'https://lab.example.org'
		});
		await runner.begin();
		await window.H.sleep(100);
	});
	expect(await page.evaluate(() => window.received)).toEqual([]);
});

test('hook-set text with HTML or a phishing string is escaped and stays out of consent and platform UI', async ({ page }) => {
	const frame = await openRuntime(page);
	const r = await frame.evaluate(async () => {
		const consentBefore = document.getElementById('consent')!.innerHTML;
		const platformBefore = document.getElementById('platform')!.innerHTML;
		const evil = '<img src=x onerror="window.__pwned=1"><a href="https://evil.example/login">Session expired: re-enter your password</a><script>window.__pwned=2</script>';
		const src = `
			osp.on('onPageInit', function (ctx, data, act) { if (data.page === 'p2') act.setVariable('hv_note', ${JSON.stringify(evil)}); });
			osp.on('onPageNext', function (ctx, data, act) {
				if (data.page === 'p2') act.rejectPage({ message: ${JSON.stringify(`${evil}‮gnp.exe`)} });
			});`;
		const { runner } = window.H.make(src, {
			manifest: { handlers: { onPageInit: { reads: [], writes: ['hv_note'] }, onPageNext: { reads: [], writes: [] } } }
		});
		await runner.begin();
		await runner.next();
		window.H.render(runner);
		const labelHtml = document.querySelector('[data-id="n2"] label')!.innerHTML;
		const rejected = await runner.next();
		window.H.render(runner);
		await window.H.sleep(200);
		const survey = document.getElementById('survey')!;
		return {
			rejected,
			labelText: document.querySelector('[data-id="n2"] label')!.textContent,
			labelHtml,
			errorText: survey.querySelector('.errors li')!.textContent,
			injected: survey.querySelectorAll('img, a, script').length,
			pwned: window.__pwned ?? null,
			consentSame: document.getElementById('consent')!.innerHTML === consentBefore,
			platformSame: document.getElementById('platform')!.innerHTML === platformBefore,
			consentHasEvil: document.getElementById('consent')!.textContent!.includes('password'),
			platformHasEvil: document.getElementById('platform')!.textContent!.includes('password'),
			title: document.querySelector('#survey h1')!.textContent
		};
	});
	expect(r.rejected).toEqual({ outcome: 'rejected' });
	expect(r.labelText).toContain('<img src=x onerror="window.__pwned=1">');
	expect(r.labelText).toContain('Session expired: re-enter your password');
	expect(r.labelHtml).toContain('&lt;img');
	expect(r.errorText).toContain('<a href="https://evil.example/login">');
	expect(r.errorText).not.toContain('‮'); // bidi override stripped
	expect(r.injected).toBe(0);
	expect(r.pwned).toBeNull();
	expect(r.consentSame && r.platformSame).toBe(true);
	expect(r.consentHasEvil || r.platformHasEvil).toBe(false);
	expect(r.title).toBe('Hooks'); // the survey title cannot be set by hooks
});
