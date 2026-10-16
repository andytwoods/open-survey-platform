// Invented sample questions for the /dev/cards gallery. No real personal data.
import type { CardDiagnostic, CardFamily, CardQuestion, PropertySchemaData, SpecChoiceList } from '#lib/cards/index.js';

const ref = (id: string) => ({ kind: 'ref', id });

/** Trimmed copies of osp-spec property schemas (just what a card reads). */
const schema = (type: string, family: string, en: string, icon: string, keys: string[]): PropertySchemaData => ({
	type,
	entity: 'question',
	family,
	label: { en },
	icon,
	properties: Object.fromEntries(keys.map((k) => [k, {}]))
});
const BASE = ['label', 'help', 'showIf', 'required', 'constraint', 'constraintMessage', 'name'];

export const SCHEMAS: Record<string, PropertySchemaData> = {
	single: schema('single', 'choice', 'Single choice', 'circle-dot', [...BASE, 'choices', 'choiceOrder']),
	multi: schema('multi', 'choice', 'Multiple choice', 'square-check', [...BASE, 'choices', 'choiceOrder']),
	text: schema('text', 'text', 'Text', 'text-cursor-input', BASE),
	date: schema('date', 'text', 'Date', 'calendar', BASE),
	integer: schema('integer', 'number', 'Whole number', 'hash', BASE),
	decimal: schema('decimal', 'number', 'Decimal number', 'calculator', BASE),
	// Provisional: osp-spec has no matrix / slider type yet.
	matrix: schema('matrix', 'matrix', 'Matrix', 'grid-3x3', [...BASE, 'choices', 'rows']),
	slider: schema('slider', 'scale', 'Slider', 'sliders-horizontal', [...BASE, 'min', 'max', 'step']),
	note: schema('note', 'note', 'Note', 'sticky-note', ['label', 'help', 'showIf'])
};

export const CHOICE_LISTS: SpecChoiceList[] = [
	{
		id: 'freq5',
		choices: [
			{ value: 1, label: 'Never' },
			{ value: 2, label: 'Rarely' },
			{ value: 3, label: 'Sometimes' },
			{ value: 4, label: 'Often' },
			{ value: 5, label: 'Always' }
		]
	}
];

export interface Sample {
	question: CardQuestion;
	diagnostics?: CardDiagnostic[];
	exportWarning?: string;
}

export const SAMPLES: Record<CardFamily, Sample[]> = {
	choice: [
		{
			question: {
				id: 'q_devices',
				type: 'multi',
				label: 'Which devices do you use in bed, ${q_name}?',
				help: 'Tick all that apply.',
				required: true,
				choiceOrder: 'shuffle',
				showIf: { kind: 'compare', op: '>=', left: ref('q_age'), right: { kind: 'int', value: 18 } },
				choices: [
					{ value: 'phone', label: 'Phone' },
					{ value: 'tablet', label: 'Tablet' },
					{ value: 'laptop', label: 'Laptop' }
				]
			},
			exportWarning: 'Shuffle not supported in XLSForm'
		},
		{
			question: {
				id: 'q_consent',
				type: 'single',
				label: 'I agree to take part',
				required: true,
				choices: [
					{ value: 1, label: 'Yes' },
					{ value: 0, label: 'No' }
				]
			}
		}
	],
	text: [
		{
			question: {
				id: 'q_study_place',
				type: 'text',
				label: 'Where do you usually study?',
				constraint: {
					kind: 'compare',
					op: '!=',
					left: ref('q_study_place'),
					right: { kind: 'text', value: 'n/a' }
				}
			}
		},
		{ question: { id: 'q_birth', type: 'date', label: 'When did you start university?' } }
	],
	number: [
		{
			question: {
				id: 'q_hours',
				type: 'integer',
				label: 'Hours of sleep on a typical night',
				required: true,
				constraint: {
					kind: 'and',
					args: [
						{ kind: 'compare', op: '>=', left: ref('q_hours'), right: { kind: 'int', value: 0 } },
						{ kind: 'compare', op: '<=', left: ref('q_hours'), right: { kind: 'int', value: 24 } }
					]
				}
			},
			diagnostics: [
				{ severity: 'warning', code: 'text.missing_translation', message: 'No German label' }
			]
		}
	],
	matrix: [
		{
			question: {
				id: 'q_study_grid',
				type: 'matrix',
				label: 'How often do you study at these times?',
				choiceList: 'freq5',
				rows: [
					{ value: 'morning', label: 'Morning' },
					{ value: 'evening', label: 'Evening' },
					{ value: 'night', label: 'After midnight' }
				]
			}
		}
	],
	scale: [
		{
			question: {
				id: 'q_quality',
				type: 'slider',
				label: 'How would you rate your sleep quality last night?',
				min: 0,
				max: 10,
				minLabel: 'Very poor',
				maxLabel: 'Excellent',
				showIf: { kind: 'answered', ref: ref('q_hours') }
			},
			diagnostics: [{ severity: 'error', code: 'ref.unknown', message: 'Unknown question q_nap' }]
		}
	],
	note: [
		{
			question: {
				id: 'q_info',
				type: 'note',
				label: 'Thanks, ${q_name}. The next questions are about your sleep over the last week.'
			}
		}
	]
};
