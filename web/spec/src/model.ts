/**
 * The `osp-survey/0.1` model (python/osp-spec/src/osp_spec/model.py, hooks.py, theme.py and
 * osp_expr/ast.py) as schema validators: the same fields in the same order, the same
 * constraints, defaults, aliases and validators. Stage 1 of `validate`.
 */

import {
	bool,
	dict,
	type Field,
	float,
	int,
	jsonValue,
	list,
	literal,
	model,
	nullable,
	str,
	tagged,
	tuple,
	union,
	type Validator,
	decimalLax
} from './schema.ts';
import { reprStr as reprName } from './py.ts';

export const SPEC_VERSION = 'osp-survey/0.1';
export const KEYWORDS = new Set(['and', 'or', 'not', 'null', 'true', 'false']);
export const RESERVED_EXTERNAL_PARAMS = ['osp_return', 'osp_token'];
export const MAX_HOOK_SOURCE_BYTES = 256 * 1024;
export const MAX_PAYLOAD_DEPTH = 4;

const IDENT = '^[A-Za-z_][A-Za-z0-9_]*$';
const Identifier = str({ pattern: IDENT, min: 1, max: 64 });
const LanguageTag = str({ pattern: '^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$' });
const DecimalText = str({ pattern: '^-?(\\d+(\\.\\d+)?)$', max: 64 });
const OutcomeKey = str({ pattern: '^(?:[A-Za-z_][A-Za-z0-9_]*|hook-failed)$', min: 1, max: 64 });
const DateText = str({ pattern: '^\\d{4}-\\d{2}-\\d{2}$' });
const Name = str({ min: 1, max: 256 });
const RedirectValue = str({ max: 256 });
const ChoiceValue = union(int(), str());
const Order = literal('fixed', 'shuffle');

const f = (name: string, v: Field['v'], extra: Partial<Field> = {}): Field => ({ name, v, ...extra });
/** An optional field: `X | None = None`. */
const opt = (name: string, v: Field['v'], extra: Partial<Field> = {}): Field => ({
	name,
	v: nullable(v),
	default: null,
	...extra
});

// --- Expressions (osp_expr.ast; lax models) ------------------------------------------------

const QuestionId = str({ pattern: IDENT });

const Ref = model('Ref', [
	f('kind', literal('ref'), { default: 'ref' }),
	f('id', QuestionId, { after: (v) => (KEYWORDS.has(v as string) ? `'${v as string}' is a reserved word and cannot be a question id` : null) })
]);

export const Expr: Validator = tagged('kind', [
	['int', model('IntLit', [f('kind', literal('int'), { default: 'int' }), f('value', int())])],
	['decimal', model('DecLit', [f('kind', literal('decimal'), { default: 'decimal' }), f('value', decimalLax)])],
	['text', model('TextLit', [f('kind', literal('text'), { default: 'text' }), f('value', str())])],
	['bool', model('BoolLit', [f('kind', literal('bool'), { default: 'bool' }), f('value', bool)])],
	['null', model('NullLit', [f('kind', literal('null'), { default: 'null' })])],
	['ref', Ref],
	[
		'compare',
		() =>
			model('Compare', [
				f('kind', literal('compare'), { default: 'compare' }),
				f('op', literal('==', '!=', '<', '<=', '>', '>=')),
				f('left', () => Expr),
				f('right', () => Expr)
			])
	],
	[
		'arith',
		() =>
			model('Arith', [
				f('kind', literal('arith'), { default: 'arith' }),
				f('op', literal('+', '-', '*', '/')),
				f('left', () => Expr),
				f('right', () => Expr)
			])
	],
	['and', () => model('And', [f('kind', literal('and'), { default: 'and' }), f('args', tuple(Expr, { min: 2 }))])],
	['or', () => model('Or', [f('kind', literal('or'), { default: 'or' }), f('args', tuple(Expr, { min: 2 }))])],
	['not', () => model('Not', [f('kind', literal('not'), { default: 'not' }), f('arg', () => Expr)])],
	['answered', model('Answered', [f('kind', literal('answered'), { default: 'answered' }), f('ref', Ref)])],
	[
		'contains',
		() =>
			model('Contains', [
				f('kind', literal('contains'), { default: 'contains' }),
				f('ref', Ref),
				f('value', () => Expr)
			])
	],
	[
		'if',
		() =>
			model('If', [
				f('kind', literal('if'), { default: 'if' }),
				f('cond', () => Expr),
				f('then', () => Expr),
				f('else_', () => Expr, { alias: 'else' })
			])
	]
]);

// --- Rich text ----------------------------------------------------------------------------

const TextRun = model('TextRun', [
	f('text', str()),
	opt('marks', list(literal('b', 'i')), {
		after: (v) => (Array.isArray(v) && new Set(v).size !== v.length ? 'a mark may appear once per run' : null)
	}),
	opt('href', str({ max: 2000 })),
	opt('lang', LanguageTag)
]);
const PipeRun = model('PipeRun', [f('pipe', str({ min: 1, max: 64 }))]);
const LineBreak = model('LineBreak', [f('br', literal(true))]);
const Inline = union(TextRun, PipeRun, LineBreak);
const RichList = model('RichList', [f('type', literal('ul', 'ol')), f('items', list(list(Inline)))]);
const RichBlock = tagged('type', [
	['p', model('Paragraph', [f('type', literal('p')), f('content', list(Inline))])],
	['h', model('Heading', [f('type', literal('h')), f('level', int({ ge: 1, le: 3 })), f('content', list(Inline))])],
	['ul', RichList],
	['ol', RichList]
]);
const RichText = model('RichText', [f('type', literal('rich')), f('blocks', list(RichBlock))]);

const Text = union(str(), RichText, dict(LanguageTag, union(str(), RichText)));
const PlainText = union(str(), dict(LanguageTag, str()));

// --- Provenance -----------------------------------------------------------------------------

const BankRef = str({ pattern: '^[A-Za-z0-9][A-Za-z0-9_.-]*$', min: 1, max: 64 });
const BankLibrary = literal('lab', 'host', 'bundled', 'file');
const Source = model('Source', [
	f('bank', BankRef),
	f('version', int({ ge: 1 })),
	f('library', BankLibrary),
	opt('item', Identifier),
	opt('checksum', str({ pattern: '^sha256:[0-9a-f]{64}$' }))
]);
const LicenceClass = literal(
	'public-domain',
	'cc0',
	'cc-by-4.0',
	'free-use',
	'author-permission',
	'free-noncommercial',
	'licensed-to-lab',
	'unknown'
);
const Instrument = model('Instrument', [
	f('bank', BankRef),
	f('version', int({ ge: 1 })),
	f('library', BankLibrary),
	opt('title', str()),
	opt('abbreviation', str()),
	opt(
		'licence',
		model('InstrumentLicence', [
			f('class_', LicenceClass, { alias: 'class' }),
			opt('holder', str()),
			opt('statement', str()),
			opt('url', str()),
			opt('evidenceDate', DateText)
		])
	),
	opt('citation', model('InstrumentCitation', [f('text', str()), opt('doi', str())]))
]);

// --- Metadata, settings, consent -------------------------------------------------------------

const Metadata = model('Metadata', [
	f('title', PlainText),
	opt('description', Text),
	f('languages', list(LanguageTag, { min: 1 })),
	opt('defaultLanguage', LanguageTag),
	opt('license', str()),
	opt('ddi', dict(str(), jsonValue)),
	opt('instruments', list(Instrument))
]);

const Retention = model('Retention', [
	f('kind', literal('days-after-close', 'after-date', 'indefinite')),
	opt('days', int({ ge: 0 })),
	opt('until', DateText)
]);
const RedirectParam = model('RedirectParam', [opt('pattern', str())]);
export const RedirectTemplate = model('RedirectTemplate', [f('url', str()), f('params', dict(Name, RedirectParam))]);
const EndRedirect = model('EndRedirect', [
	f('template', Name),
	f('params', dict(Name, RedirectValue), { default: () => new Map() }),
	f('delay', int({ ge: 0, le: 60 }), { default: 5 }),
	f('mode', literal('auto', 'link'), { default: 'auto' }),
	opt('label', Text)
]);
const Ending = model('Ending', [
	opt('title', Text),
	opt('body', Text),
	f('status', literal('auto', 'none'), { default: 'auto' }),
	f('summary', literal('none', 'answers'), { default: 'none' }),
	opt('redirect', EndRedirect)
]);

const HexColour = str({ pattern: '^#[0-9a-fA-F]{6}$' });
const Palette = model(
	'Palette',
	['accent', 'background', 'surface', 'text', 'muted', 'error', 'focus'].map((k) => f(k, HexColour))
);
const Theme = model('Theme', [
	f('themeVersion', literal('osp-theme/0.1'), { default: 'osp-theme/0.1' }),
	opt('preset', literal('clean', 'warm', 'high-contrast', 'dark', 'compact')),
	f('colours', model('Colours', [f('light', Palette), f('dark', Palette)])),
	opt('logoAssetId', str({ pattern: '^[A-Za-z0-9_-]{1,64}$' })),
	opt('headerText', PlainText),
	f('font', literal('system-sans', 'system-serif', 'system-rounded'), { default: 'system-sans' }),
	f('baseSize', int({ ge: 12, le: 32 }), { default: 16 }),
	f('lineSpacing', float({ ge: 1.0, le: 2.5 }), { default: 1.5 }),
	f('radius', int({ ge: 0, le: 32 }), { default: 6 }),
	f('density', literal('comfortable', 'compact'), { default: 'comfortable' }),
	f('buttonStyle', literal('filled', 'outline'), { default: 'filled' }),
	f('choiceStyle', literal('list', 'cards', 'buttons'), { default: 'list' }),
	f('mode', literal('light', 'dark', 'auto'), { default: 'auto' })
]);

const Settings = model('Settings', [
	f('backNavigation', bool, { default: true }),
	f('saveMode', literal('every-page', 'end-only'), { default: 'every-page' }),
	f('localCopy', literal('browser', 'memory'), { default: 'browser' }),
	f('resumeExpiryDays', int({ ge: 1, le: 3650 }), { default: 30 }),
	opt('retention', Retention),
	opt('theme', Theme),
	f('endings', dict(OutcomeKey, Ending), { default: () => new Map() }),
	f('redirectTemplates', dict(Name, RedirectTemplate), { default: () => new Map() })
]);

const Consent = model('Consent', [
	f('text', Text),
	f('agreeLabel', Text, { default: 'I agree' }),
	f('declineLabel', Text, { default: 'I do not agree' }),
	f('declineOutcome', Identifier, { default: 'declined' }),
	f('countDeclines', bool, { default: false })
]);

// --- Choices and questions --------------------------------------------------------------------

const Choice = model('Choice', [f('value', ChoiceValue), f('label', Text)]);
const ChoiceList = model('ChoiceList', [f('id', Identifier), f('choices', list(Choice, { min: 1 }))]);

const CustomKey = str({ pattern: '^[a-z][a-z0-9_]{0,39}$' });
const CustomValue = union(str(), int(), float(), bool);

const questionBase = (): Field[] => [
	f('id', Identifier),
	f('label', Text),
	opt('help', Text),
	opt('showIf', Expr),
	opt('custom', dict(CustomKey, CustomValue, { max: 40 })),
	opt('source', Source)
];
const answerableBase = (): Field[] => [
	...questionBase(),
	opt('name', Identifier),
	f('required', bool, { default: false }),
	opt('constraint', Expr),
	opt('constraintMessage', Text)
];
const choiceBase = (): Field[] => [
	...answerableBase(),
	opt('choiceList', Identifier),
	opt('choices', list(Choice, { min: 1 })),
	f('choiceOrder', Order, { default: 'fixed' })
];
const IntOrDecimal = union(int(), DecimalText);

const Question = tagged('type', [
	[
		'integer',
		model('IntegerQuestion', [...answerableBase(), f('type', literal('integer')), opt('min', int()), opt('max', int())])
	],
	[
		'decimal',
		model('DecimalQuestion', [
			...answerableBase(),
			f('type', literal('decimal')),
			opt('min', IntOrDecimal),
			opt('max', IntOrDecimal)
		])
	],
	[
		'text',
		model('TextQuestion', [...answerableBase(), f('type', literal('text')), f('multiline', bool, { default: false })])
	],
	['single', model('SingleQuestion', [...choiceBase(), f('type', literal('single'))])],
	['multi', model('MultiQuestion', [...choiceBase(), f('type', literal('multi'))])],
	['date', model('DateQuestion', [...answerableBase(), f('type', literal('date'))])],
	[
		'matrix',
		model('MatrixQuestion', [
			...questionBase(),
			f('type', literal('matrix')),
			opt('name', Identifier),
			f('required', bool, { default: false }),
			f(
				'rows',
				list(model('MatrixRow', [f('id', Identifier), f('label', Text), opt('required', bool)]), { min: 1 })
			),
			opt('choiceList', Identifier),
			opt('choices', list(Choice, { min: 1 }))
		])
	],
	[
		'slider',
		model('SliderQuestion', [
			...answerableBase(),
			f('type', literal('slider')),
			f('valueType', literal('integer', 'decimal'), { default: 'integer' }),
			f('min', IntOrDecimal, { default: 0 }),
			f('max', IntOrDecimal, { default: 100 }),
			f('step', IntOrDecimal, { default: 1 }),
			opt('minLabel', Text),
			opt('maxLabel', Text)
		])
	],
	['note', model('NoteQuestion', [...questionBase(), f('type', literal('note'))])]
]);

const Page = model('Page', [
	f('id', Identifier),
	opt('title', Text),
	opt('showIf', Expr),
	f('items', list(Question, { min: 1 })),
	f('itemOrder', Order, { default: 'fixed' }),
	opt('source', Source)
]);
const Block = model('Block', [
	f('id', Identifier),
	opt('title', str()),
	f('pages', list(Page, { min: 1 })),
	opt('source', Source)
]);

// --- Variables, quotas, flow ------------------------------------------------------------------

const Variable = tagged('kind', [
	[
		'embedded',
		model('EmbeddedVariable', [
			f('id', Identifier),
			opt('name', Identifier),
			f('kind', literal('embedded')),
			f('valueType', literal('text', 'integer', 'decimal'), { default: 'text' }),
			f('source', literal('url'), { default: 'url' }),
			f('param', str()),
			opt('default', union(str(), int()))
		])
	],
	[
		'assigned',
		model('AssignedVariable', [
			f('id', Identifier),
			opt('name', Identifier),
			f('kind', literal('assigned')),
			f('levels', list(ChoiceValue, { min: 1 }))
		])
	],
	[
		'computed',
		model('ComputedVariable', [f('id', Identifier), opt('name', Identifier), f('kind', literal('computed')), f('expr', Expr)])
	]
]);

const Quota = model('Quota', [
	f('id', Identifier),
	f('when', Expr),
	f('limit', int({ ge: 0 })),
	f('countOn', literal('complete'), { default: 'complete' }),
	f('onFull', model('QuotaFull', [opt('block', Identifier), f('outcome', Identifier)]))
]);

const FlowNode: Validator = tagged('type', [
	['block', model('BlockNode', [f('type', literal('block')), f('id', Identifier), f('block', Identifier)])],
	[
		'branch',
		() =>
			model('BranchNode', [
				f('type', literal('branch')),
				f('id', Identifier),
				f('if_', Expr, { alias: 'if' }),
				f('then', list(FlowNode)),
				f('else_', list(FlowNode), { alias: 'else', default: () => [] })
			])
	],
	[
		'randomiser',
		() =>
			model('RandomiserNode', [
				f('type', literal('randomiser')),
				f('id', Identifier),
				f('children', list(FlowNode, { min: 1 })),
				opt('pick', int({ ge: 1 }))
			])
	],
	[
		'assign',
		model('AssignNode', [f('type', literal('assign')), f('id', Identifier), f('variables', list(Identifier, { min: 1 }))])
	],
	['quotaCheck', model('QuotaCheckNode', [f('type', literal('quotaCheck')), f('id', Identifier), f('quota', Identifier)])],
	[
		'externalTask',
		model('ExternalTaskNode', [
			f('type', literal('externalTask')),
			f('id', Identifier),
			f('template', Name),
			f('params', dict(Name, RedirectValue), { default: () => new Map() }),
			f('returns', list(Identifier), { default: () => [] })
		])
	],
	[
		'end',
		model('EndNode', [
			f('type', literal('end')),
			f('id', Identifier),
			f('outcome', Identifier, { default: 'complete' }),
			opt('message', Text)
		])
	]
]);

// --- Hooks (osp_spec.hooks) -------------------------------------------------------------------

const HOOK_EVENTS = [
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
] as const;

const NumberSchema = model('HookNumberSchema', [
	f('type', literal('number', 'integer')),
	opt('minimum', union(int(), float())),
	opt('maximum', union(int(), float()))
]);
const Payload: Validator = tagged('type', [
	[
		'string',
		model('HookStringSchema', [
			f('type', literal('string')),
			opt('maxLength', int({ ge: 0 })),
			opt('pattern', str()),
			opt('enum', list(str()))
		])
	],
	['number', NumberSchema],
	['integer', NumberSchema],
	['boolean', model('HookBooleanSchema', [f('type', literal('boolean'))])],
	['null', model('HookNullSchema', [f('type', literal('null'))])],
	[
		'object',
		() =>
			model('HookObjectSchema', [
				f('type', literal('object')),
				f('properties', dict(Name, Payload)),
				opt('required', list(Name))
			])
	],
	[
		'array',
		() =>
			model('HookArraySchema', [f('type', literal('array')), f('items', () => Payload), f('maxItems', int({ ge: 0, le: 1000 }))])
	]
]);

function depth(schema: unknown, d: number): number {
	const s = schema as Record<string, unknown>;
	if (s.type === 'object') {
		let best = d;
		for (const v of (s.properties as Map<string, unknown>).values()) best = Math.max(best, depth(v, d + 1));
		return best;
	}
	if (s.type === 'array') return depth(s.items, d + 1);
	return d;
}

function utf8Length(s: string): number {
	let n = 0;
	for (const ch of s) {
		const cp = ch.codePointAt(0)!;
		n += cp < 0x80 ? 1 : cp < 0x800 ? 2 : cp < 0x10000 ? 3 : 4;
	}
	return n;
}

const HookParent = model('HookParent', [f('origin', str()), f('messages', dict(Name, Payload))], {
	after(v) {
		for (const [name, schema] of v.messages as Map<string, unknown>) {
			if (depth(schema, 0) > MAX_PAYLOAD_DEPTH) {
				return `message schema ${reprName(name)} is nested deeper than ${MAX_PAYLOAD_DEPTH}`;
			}
		}
		return null;
	}
});
const Hooks = model('Hooks', [
	f('format', literal('osp-hooks/1')),
	f('source', str(), {
		after: (v) => (utf8Length(v as string) > MAX_HOOK_SOURCE_BYTES ? `source is larger than ${MAX_HOOK_SOURCE_BYTES} bytes` : null)
	}),
	f(
		'handlers',
		dict(
			literal(...HOOK_EVENTS),
			model('HookHandler', [
				f('reads', list(Identifier)),
				f('writes', list(Identifier)),
				opt('timeoutMs', int({ ge: 1, le: 5000 }))
			])
		)
	),
	opt('urlParams', list(Name)),
	opt('redirects', dict(Name, RedirectTemplate)),
	opt('parent', HookParent),
	opt('exportsConfirmedFor', str())
]);

// --- Survey -----------------------------------------------------------------------------------

/** A fresh `Settings()` (the default when a survey has none). */
function defaultSettings(): unknown {
	const r = Settings.run({});
	return r.ok ? r.value : null;
}

export const Survey = model('Survey', [
	f('specVersion', literal(SPEC_VERSION)),
	f('id', Identifier),
	opt('version', int({ ge: 1 })),
	f('metadata', Metadata),
	f('settings', Settings, { default: defaultSettings }),
	opt('consent', Consent),
	f('choiceLists', list(ChoiceList), { default: () => [] }),
	f('variables', list(Variable), { default: () => [] }),
	f('blocks', list(Block), { default: () => [] }),
	f('quotas', list(Quota), { default: () => [] }),
	f('flow', list(FlowNode), { default: () => [] }),
	opt('hooks', Hooks)
]);
