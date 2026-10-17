import { describe, expect, it } from 'vitest';
import {
	HOOK_EVENTS,
	advancedParts,
	draftOf,
	hookDiagnostics,
	hooksOf,
	hooksOp,
	manifestOf,
	parseIds,
	registeredEvents,
	sameManifest,
	starterManifest,
	staticProblems,
	type HookManifest
} from './hooks';

const MANIFEST: HookManifest = {
	format: 'osp-hooks/1',
	source: "osp.on('onPageShown', function (ctx, d, act) { act.addParadata('t', ctx.trial); });",
	handlers: { onPageShown: { reads: ['a', 'b'], writes: [] }, onPageNext: { reads: [], writes: ['hv'], timeoutMs: 1500 } },
	urlParams: ['PID']
};

describe('hooks model', () => {
	it('reads the manifest from the survey, or null', () => {
		expect(hooksOf({ hooks: MANIFEST })).toBe(MANIFEST);
		expect(hooksOf({})).toBeNull();
		expect(hooksOf({ hooks: { source: 1 } })).toBeNull();
		expect(hooksOp(null)).toEqual({ op: 'set_hooks', params: { hooks: null } });
	});

	it('lists every sandbox event once, in run order', () => {
		expect(HOOK_EVENTS.map((e) => e.id)).toEqual([
			'onStart',
			'onResume',
			'onPageInit',
			'onPageShown',
			'onAnswer',
			'onPageNext',
			'onBack',
			'onValidationError',
			'onBeforeSubmit',
			'onSubmitted'
		]);
	});

	it('round-trips a manifest through the draft, keeping what the editor does not show', () => {
		const draft = draftOf(MANIFEST);
		expect(draft.handlers.onPageShown).toEqual({ on: true, reads: 'a, b', timeoutMs: '' });
		expect(draft.handlers.onPageNext).toEqual({ on: true, reads: '', timeoutMs: '1500' });
		expect(draft.handlers.onStart).toEqual({ on: false, reads: '', timeoutMs: '' });
		const { manifest, problems } = manifestOf(draft, MANIFEST);
		expect(problems).toEqual([]);
		expect(manifest).toEqual(MANIFEST); // writes and urlParams survive
		expect(sameManifest(manifest, MANIFEST)).toBe(true);
	});

	it('reports a bad timeout or id before anything is sent', () => {
		const draft = draftOf(MANIFEST);
		draft.handlers.onPageNext!.timeoutMs = '9000';
		draft.handlers.onPageShown!.reads = 'a, 1bad';
		const { problems } = manifestOf(draft, MANIFEST);
		expect(problems.map((p) => p.pointer)).toEqual(['/hooks/handlers/onPageShown/reads', '/hooks/handlers/onPageNext/timeoutMs']);
		expect(parseIds(' a,b ;c\n d ')).toEqual(['a', 'b', 'c', 'd']);
	});

	it('finds the events a script registers, and what will not run', () => {
		expect(registeredEvents(MANIFEST.source)).toEqual(['onPageShown']);
		expect(registeredEvents('osp.on("onStart", f); osp . on ( `onBack` , g); osp.on(ev, h)')).toEqual(['onStart', 'onBack']);
		const problems = staticProblems({
			...MANIFEST,
			source: "osp.on('onStart', f); osp.on('onExplode', g); osp.on('onPageShown', h);"
		});
		expect(problems.map((p) => p.message)).toEqual([
			expect.stringContaining('onPageNext is handled but the script never registers it'),
			expect.stringContaining('registers onStart but it is not handled'),
			expect.stringContaining("osp.on('onExplode') is not an event")
		]);
		expect(staticProblems({ ...MANIFEST, handlers: {} })[0]!.message).toMatch(/never runs/);
		expect(staticProblems(starterManifest())).toEqual([]);
	});

	it('keeps only the server diagnostics about the manifest', () => {
		const diags = [{ pointer: '/hooks/handlers/onStart/reads/0' }, { pointer: '/hooks' }, { pointer: '/hooksy' }, { pointer: '/blocks/0' }];
		expect(hookDiagnostics(diags).map((d) => d.pointer)).toEqual(['/hooks/handlers/onStart/reads/0', '/hooks']);
	});

	it('names the parts only the JSON view edits', () => {
		expect(advancedParts(MANIFEST)).toEqual(['URL parameters: PID', 'variable writes: onPageNext → hv']);
		expect(advancedParts(starterManifest())).toEqual([]);
		expect(advancedParts(null)).toEqual([]);
	});
});
