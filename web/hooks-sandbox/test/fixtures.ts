/**
 * Shared test plan + manifest (node unit tests and the Playwright harness both use these).
 *
 *   p1: q1 (integer), q2 (text)
 *   p2: n2 (note piping hv_note), q5 (text, shown only if hv_flag is true)
 *   branch hv_score >= 10 → p3 (q3) else p4 (q4)
 *
 * hv_score and hv_flag are flow-critical (a branch and a show-if read them); hv_note is not.
 */

import { withChecksum, type FlowNode, type Item, type Plan } from '@osp/engine';
import { sourceChecksum, type HookManifest } from '../src/manifest.ts';

const t = (s: string) => ({ en: [s] });

function item(id: string, page: string, type: Item['type'], extra: Record<string, unknown> = {}): Item {
	if (type === 'note') return { id, page, type, label: t(id), ...extra } as Item;
	return { id, page, type, label: t(id), name: id, required: false, ...extra } as Item;
}

export function hookPlan(): Plan {
	const items: Record<string, Item> = {
		q1: item('q1', 'p1', 'integer'),
		q2: item('q2', 'p1', 'text'),
		n2: item('n2', 'p2', 'note', { label: { en: ['Hello ', { pipe: 'hv_note' }, '!'] } }),
		q5: item('q5', 'p2', 'text', { showIf: { kind: 'ref', id: 'hv_flag' } }),
		q3: item('q3', 'p3', 'text'),
		q4: item('q4', 'p4', 'text')
	};
	const pages: Plan['pages'] = {};
	const blocks: Plan['blocks'] = {};
	for (const p of ['p1', 'p2', 'p3', 'p4']) {
		pages[p] = { id: p, block: `b_${p}`, items: Object.values(items).filter((i) => i.page === p).map((i) => i.id), itemOrder: 'fixed' };
		blocks[`b_${p}`] = { id: `b_${p}`, pages: [p] };
	}
	const block = (p: string): FlowNode => ({ type: 'block', id: `n_${p}`, block: `b_${p}`, pages: [p] });
	return withChecksum({
		planVersion: 'osp-runtime-plan/1',
		engineVersion: '1',
		survey: { id: 'srv_hooks', version: 1, specVersion: 'osp-survey/0.1', seedVersion: '1' },
		languages: ['en'],
		defaultLanguage: 'en',
		title: t('Hooks'),
		settings: { backNavigation: true },
		items,
		questions: ['q1', 'q2', 'q5', 'q3', 'q4'],
		pages,
		blocks,
		variables: {
			hv_score: { id: 'hv_score', kind: 'hook', name: 'hv_score', valueType: 'integer' },
			hv_flag: { id: 'hv_flag', kind: 'hook', name: 'hv_flag', valueType: 'boolean' },
			hv_note: { id: 'hv_note', kind: 'hook', name: 'hv_note', valueType: 'text' },
			hv_dec: { id: 'hv_dec', kind: 'hook', name: 'hv_dec', valueType: 'decimal' }
		},
		quotas: {},
		flow: [
			block('p1'),
			block('p2'),
			{
				type: 'branch',
				id: 'br',
				if: { kind: 'compare', op: '>=', left: { kind: 'ref', id: 'hv_score' }, right: { kind: 'int', value: 10 } },
				then: [block('p3')],
				else: [block('p4')]
			}
		]
	});
}

export const PARENT_ORIGIN = 'https://lab.example.org';

export function hookManifest(source: string, extra: Partial<HookManifest> = {}): HookManifest {
	return {
		format: 'osp-hooks/1',
		source,
		handlers: {
			onStart: { reads: [], writes: ['hv_note'] },
			onResume: { reads: [], writes: [] },
			onPageInit: { reads: ['q1'], writes: ['hv_flag', 'hv_note'] },
			onPageShown: { reads: [], writes: [] },
			onAnswer: { reads: ['q1'], writes: ['hv_note'] },
			onPageNext: { reads: ['q1', 'q2'], writes: ['hv_score', 'hv_dec'] },
			onBack: { reads: [], writes: [] },
			onValidationError: { reads: [], writes: [] },
			onBeforeSubmit: { reads: ['q1'], writes: ['hv_note'] },
			onSubmitted: { reads: [], writes: [] }
		},
		urlParams: ['PROLIFIC_PID'],
		redirects: {
			prolific: { url: 'https://app.prolific.com/submissions/complete?cc={code}', params: { code: { pattern: '[A-Z0-9]{4,12}' } } }
		},
		parent: {
			origin: PARENT_ORIGIN,
			messages: {
				progress: { type: 'object', properties: { page: { type: 'integer', minimum: 0, maximum: 1000 } }, required: ['page'] }
			}
		},
		exportsConfirmedFor: sourceChecksum(source),
		...extra
	};
}
