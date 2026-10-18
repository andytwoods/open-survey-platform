import { describe, expect, it } from 'vitest';
import type { PanelDiagnostic } from '../properties/types';
import { BUILTIN_PIPES, ENDING_PIPES, flaggedPipes, pipeCandidates, pipeProblems } from './pipes';

const survey = {
	metadata: { languages: ['en'] },
	variables: [
		{ id: 'cond', kind: 'assigned', levels: ['a', 'b'] },
		{ id: 'pid', kind: 'embedded', label: { en: 'Prolific id' } },
		{ nope: true }
	],
	blocks: [
		{
			id: 'b1',
			pages: [
				{
					id: 'p1',
					items: [
						{ id: 'note', type: 'note', label: 'Welcome' },
						{ id: 'age', type: 'integer', label: { en: 'Your age' } },
						{ id: 'grid', type: 'matrix', label: 'Rate', rows: [{ id: 'r1', label: 'One' }], choices: [{ value: 'a', label: 'A' }] }
					]
				},
				{ id: 'p2', items: [{ id: 'later', type: 'text', label: 'Later' }] }
			]
		}
	]
};

describe('pipeCandidates', () => {
	it('lists earlier questions (rows as matrix_row), variables and built-ins', () => {
		const ids = pipeCandidates(survey, { before: 'later' }).map((c) => c.id);
		expect(ids).toEqual(['age', 'grid_r1', 'cond', 'pid', ...BUILTIN_PIPES.map((b) => b.id)]);
		const byId = Object.fromEntries(pipeCandidates(survey).map((c) => [c.id, c]));
		expect(byId.age).toEqual({ id: 'age', label: 'Your age', group: 'Earlier questions' });
		expect(byId.pid!.label).toBe('Prolific id');
		expect(byId.cond!.label).toBe('assigned variable');
	});

	it('stops at the target: a question sees nothing from itself on; a page sees what is before it', () => {
		expect(pipeCandidates(survey, { before: 'age' }).filter((c) => c.group === 'Earlier questions')).toEqual([]);
		expect(pipeCandidates(survey, { before: 'p2' }).filter((c) => c.group === 'Earlier questions').map((c) => c.id)).toEqual(['age', 'grid_r1']);
		expect(pipeCandidates(survey, { before: 'grid' }).filter((c) => c.group === 'Earlier questions').map((c) => c.id)).toEqual(['age']);
	});

	it('an unknown target, or none, lists every question; endings add the end-of-session built-ins', () => {
		const all = pipeCandidates(survey, { before: 'ghost' }).filter((c) => c.group === 'Earlier questions').map((c) => c.id);
		expect(all).toEqual(['age', 'grid_r1', 'later']);
		expect(pipeCandidates(survey, { ending: true }).map((c) => c.id)).toEqual(expect.arrayContaining(ENDING_PIPES.map((b) => b.id)));
		expect(pipeCandidates(null)).toEqual([...BUILTIN_PIPES]);
		expect(pipeCandidates({ blocks: 'nope', variables: 3 })).toEqual([...BUILTIN_PIPES]);
	});
});

describe('pipeProblems', () => {
	const rich = { en: { type: 'rich', blocks: [{ type: 'p', content: [{ text: 'Hi ' }, { pipe: 'ghost' }, { text: ' and ' }, { pipe: 'later' }] }] } };
	const diags: PanelDiagnostic[] = [
		{ severity: 'error', code: 'ref.unknown', message: 'ghost is not a question', pointer: '/blocks/0/pages/0/items/0/label/en/blocks/0/content/1' },
		{ severity: 'error', code: 'ref.forward', message: "'later' comes after this item", pointer: '/blocks/0/pages/0/items/0/label/en/blocks/0/content/3' },
		{ severity: 'warning', code: 'text.missing_translation', message: 'no text for: de', pointer: '/blocks/0/pages/0/items/0/label' },
		{ severity: 'error', code: 'ref.unknown', message: 'elsewhere', pointer: '/blocks/0/pages/0/items/1/label' }
	];

	it('resolves node pointers through the value and ignores other fields and codes', () => {
		const p = pipeProblems(rich, 'en', diags, '/blocks/0/pages/0/items/0/label');
		expect([...p]).toEqual([
			['ghost', 'ghost is not a question'],
			['later', "'later' comes after this item"]
		]);
	});

	it('matches a plain string field by the id named in the message', () => {
		const d: PanelDiagnostic[] = [
			{ severity: 'error', code: 'pipe.invalid', message: "'${a b}' is not a valid reference", pointer: '/x/label' },
			{ severity: 'error', code: 'ref.unknown', message: 'unknown question age (piped)', pointer: '/x/label' }
		];
		const p = pipeProblems('Hi ${age} ${a b}', 'en', d, '/x/label');
		expect(p.get('a b')).toContain('not a valid');
		expect(p.get('age')).toContain('unknown question');
		expect(flaggedPipes('Hi ${age}', p)).toEqual(['age']);
		expect(flaggedPipes('Hi ${other}', p)).toEqual([]);
	});

	it('never throws on odd input', () => {
		expect(pipeProblems(undefined, 'en', undefined, '').size).toBe(0);
		expect(pipeProblems(3, 'en', [{ severity: 'error', code: 'ref.x', message: '', pointer: '/a/blocks/9/content/9' }], '/a').size).toBe(0);
	});
});
