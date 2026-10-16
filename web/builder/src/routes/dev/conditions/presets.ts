import type { ExprNode } from '#lib/conditions/index.js';

// Starting conditions for the /dev/conditions page (invented content, no real data).
const ref = (id: string) => ({ kind: 'ref', id });

export const PRESETS: { id: string; label: string; value: ExprNode | null }[] = [
	{ id: 'empty', label: 'No condition', value: null },
	{
		id: 'deleted',
		label: 'Refers to a deleted question',
		value: {
			kind: 'and',
			args: [
				{ kind: 'compare', op: '>=', left: ref('age'), right: { kind: 'int', value: 18 } },
				{ kind: 'compare', op: '==', left: ref('q_gone'), right: { kind: 'int', value: 1 } }
			]
		}
	},
	{
		id: 'forward',
		label: 'Refers to a later question',
		value: { kind: 'compare', op: '>', left: ref('later'), right: { kind: 'int', value: 2 } }
	},
	{
		id: 'excludes',
		label: 'Excludes (may be unanswered)',
		value: { kind: 'not', arg: { kind: 'contains', ref: ref('colours'), value: { kind: 'text', value: 'red' } } }
	},
	{
		id: 'complex',
		label: 'Too complex for the visual editor',
		value: {
			kind: 'compare',
			op: '>',
			left: { kind: 'arith', op: '+', left: ref('age'), right: { kind: 'int', value: 1 } },
			right: { kind: 'int', value: 30 }
		}
	}
];
