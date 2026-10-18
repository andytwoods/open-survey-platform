/**
 * The `osp-spec` / `osp-expr` models the ops validate themselves, as `pyd.ts` schemas:
 * rich text, `Ending`, `RedirectTemplate`, `Source`, the hook manifest (`osp_spec.hooks`),
 * the theme (`osp_spec.theme.Theme`) and the expression AST (`osp_expr.ast.EXPR_ADAPTER`),
 * plus the field lists `set_property` checks against (`model_fields` of each model class).
 * The whole-survey model is not here: that is the injected validator's job (CE4).
 */

import { S, type Field, type ModelSchema, type ModelVal, type Schema, type Val } from './pyd.ts';
import { reprStr } from './py.ts';

// --- constrained strings (osp_spec.model) ------------------------------------------------------

export const IDENT_PATTERN = '^[A-Za-z_][A-Za-z0-9_]*$';
export const Identifier = S.str({ pattern: IDENT_PATTERN, min: 1, max: 64 });
export const LanguageTag = S.str({ pattern: '^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$' });
export const OutcomeKey = S.str({ pattern: '^(?:[A-Za-z_][A-Za-z0-9_]*|hook-failed)$', min: 1, max: 64 });
export const Name = S.str({ min: 1, max: 256 });
const RedirectValue = S.str({ max: 256 });
const BankRef = S.str({ pattern: '^[A-Za-z0-9][A-Za-z0-9_.-]*$', min: 1, max: 64 });
const Checksum = S.str({ pattern: '^sha256:[0-9a-f]{64}$' });

const opt = (name: string, schema: Schema, extra: Partial<Field> = {}): Field => ({
	name,
	schema: S.nullable(schema),
	default: null,
	...extra
});
const req = (name: string, schema: Schema, extra: Partial<Field> = {}): Field => ({ name, schema, ...extra });
const def = (name: string, schema: Schema, value: Field['default']): Field => ({ name, schema, default: value });

// --- rich text -------------------------------------------------------------------------------

const TextRun = S.model('TextRun', [
	req('text', S.str()),
	opt('marks', S.list(S.literal('b', 'i')), {
		after: (v: Val) => (Array.isArray(v) && new Set(v as string[]).size !== v.length ? 'a mark may appear once per run' : null)
	}),
	opt('href', S.str({ max: 2000 })),
	opt('lang', LanguageTag)
]);
const PipeRun = S.model('PipeRun', [req('pipe', S.str({ min: 1, max: 64 }))]);
const LineBreak = S.model('LineBreak', [req('br', S.literal(true))]);
const Inline = S.union(['TextRun', TextRun], ['PipeRun', PipeRun], ['LineBreak', LineBreak]);
const Paragraph = S.model('Paragraph', [req('type', S.literal('p')), req('content', S.list(Inline))]);
const Heading = S.model('Heading', [
	req('type', S.literal('h')),
	req('level', S.int({ ge: 1, le: 3 })),
	req('content', S.list(Inline))
]);
const RichList = S.model('RichList', [req('type', S.literal('ul', 'ol')), req('items', S.list(S.list(Inline)))]);
const RichBlock = S.tagged('type', [
	['p', Paragraph],
	['h', Heading],
	['ul', RichList],
	['ol', RichList]
]);
export const RichText = S.model('RichText', [req('type', S.literal('rich')), req('blocks', S.list(RichBlock))]);

/** `Text`: plain, rich, or per language (each plain or rich). */
export const Text = S.union(
	['str', S.str()],
	['RichText', RichText],
	['dict[constrained-str,union[str,...]]', S.dict(LanguageTag, S.union(['str', S.str()], ['RichText', RichText]))]
);
/** `PlainText`: plain, or per language. */
export const PlainText = S.union(['str', S.str()], ['dict[constrained-str,str]', S.dict(LanguageTag, S.str())]);

// --- endings and redirects ---------------------------------------------------------------------

export const RedirectParam = S.model('RedirectParam', [opt('pattern', S.str())]);
export const RedirectTemplate = S.model('RedirectTemplate', [req('url', S.str()), req('params', S.dict(Name, RedirectParam))]);

const EndRedirect = S.model('EndRedirect', [
	req('template', Name),
	def('params', S.dict(Name, RedirectValue), () => ({})),
	def('delay', S.int({ ge: 0, le: 60 }), 5),
	def('mode', S.literal('auto', 'link'), 'auto'),
	opt('label', Text)
]);
export const Ending = S.model('Ending', [
	opt('title', Text),
	opt('body', Text),
	def('status', S.literal('auto', 'none'), 'auto'),
	def('summary', S.literal('none', 'answers'), 'none'),
	opt('redirect', EndRedirect)
]);

// --- provenance ------------------------------------------------------------------------------

export const Source = S.model('Source', [
	req('bank', BankRef),
	req('version', S.int({ ge: 1 })),
	req('library', S.literal('lab', 'host', 'bundled', 'file')),
	opt('item', Identifier),
	opt('checksum', Checksum)
]);

// --- hooks (osp_spec.hooks) ------------------------------------------------------------------

export const HOOK_EVENTS = [
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
];
const MAX_HOOK_TIMEOUT_MS = 5000;
const MAX_HOOK_SOURCE_BYTES = 256 * 1024;
const MAX_PAYLOAD_DEPTH = 4;

const HookHandler = S.model('HookHandler', [
	req('reads', S.list(Identifier)),
	req('writes', S.list(Identifier)),
	opt('timeoutMs', S.int({ ge: 1, le: MAX_HOOK_TIMEOUT_MS }))
]);
const HookNumber = S.union(['int', S.int()], ['float', S.float({ finite: true })]);
const HookStringSchema = S.model('HookStringSchema', [
	req('type', S.literal('string')),
	opt('maxLength', S.int({ ge: 0 })),
	opt('pattern', S.str()),
	opt('enum', S.list(S.str()))
]);
const HookNumberSchema = S.model('HookNumberSchema', [
	req('type', S.literal('number', 'integer')),
	opt('minimum', HookNumber),
	opt('maximum', HookNumber)
]);
const HookBooleanSchema = S.model('HookBooleanSchema', [req('type', S.literal('boolean'))]);
const HookNullSchema = S.model('HookNullSchema', [req('type', S.literal('null'))]);
const Payload: Schema = S.lazy(() => PayloadUnion);
const HookObjectSchema = S.model('HookObjectSchema', [
	req('type', S.literal('object')),
	req('properties', S.dict(Name, Payload)),
	opt('required', S.list(Name))
]);
const HookArraySchema = S.model('HookArraySchema', [
	req('type', S.literal('array')),
	req('items', Payload),
	req('maxItems', S.int({ ge: 0, le: 1000 }))
]);
const PayloadUnion: Schema = S.tagged('type', [
	['string', HookStringSchema],
	['number', HookNumberSchema],
	['integer', HookNumberSchema],
	['boolean', HookBooleanSchema],
	['null', HookNullSchema],
	['object', HookObjectSchema],
	['array', HookArraySchema]
]);

function depth(schema: Val, d: number): number {
	const m = schema as ModelVal;
	if (m.schema === HookObjectSchema) {
		const props = m.get('properties') as Record<string, Val>;
		return Math.max(d, ...Object.values(props).map((v) => depth(v, d + 1)));
	}
	if (m.schema === HookArraySchema) return depth(m.get('items'), d + 1);
	return d;
}

const HookParent = S.model('HookParent', [req('origin', S.str()), req('messages', S.dict(Name, Payload))], (v) => {
	const messages = v.get('messages') as Record<string, Val>;
	for (const name of Object.keys(messages)) {
		if (depth(messages[name]!, 0) > MAX_PAYLOAD_DEPTH) {
			return `message schema ${reprStr(name)} is nested deeper than ${MAX_PAYLOAD_DEPTH}`;
		}
	}
	return null;
});

/** UTF-8 length with `surrogatepass` (a lone surrogate is 3 bytes). */
function utf8Length(s: string): number {
	let n = 0;
	for (const ch of s) {
		const cp = ch.codePointAt(0)!;
		n += cp < 0x80 ? 1 : cp < 0x800 ? 2 : cp < 0x10000 ? 3 : 4;
	}
	return n;
}

export const Hooks = S.model('Hooks', [
	req('format', S.literal('osp-hooks/1')),
	req('source', S.str(), {
		after: (v: Val) => (utf8Length(v as string) > MAX_HOOK_SOURCE_BYTES ? `source is larger than ${MAX_HOOK_SOURCE_BYTES} bytes` : null)
	}),
	req('handlers', S.dict(S.literal(...HOOK_EVENTS), HookHandler)),
	opt('urlParams', S.list(Name)),
	opt('redirects', S.dict(Name, RedirectTemplate)),
	opt('parent', HookParent),
	opt('exportsConfirmedFor', S.str())
]);

// --- theme (osp_spec.theme) ------------------------------------------------------------------

const HexColour = S.str({ pattern: '^#[0-9a-fA-F]{6}$' });
const Palette = S.model(
	'Palette',
	['accent', 'background', 'surface', 'text', 'muted', 'error', 'focus'].map((n) => req(n, HexColour))
);
const Colours = S.model('Colours', [req('light', Palette), req('dark', Palette)]);
export const Theme = S.model('Theme', [
	def('themeVersion', S.literal('osp-theme/0.1'), 'osp-theme/0.1'),
	opt('preset', S.literal('clean', 'warm', 'high-contrast', 'dark', 'compact')),
	req('colours', Colours),
	opt('logoAssetId', S.str({ pattern: '^[A-Za-z0-9_-]{1,64}$' })),
	opt('headerText', PlainText),
	def('font', S.literal('system-sans', 'system-serif', 'system-rounded'), 'system-sans'),
	def('baseSize', S.int({ ge: 12, le: 32 }), 16),
	def('lineSpacing', S.float({ ge: 1.0, le: 2.5 }), 1.5),
	def('radius', S.int({ ge: 0, le: 32 }), 6),
	def('density', S.literal('comfortable', 'compact'), 'comfortable'),
	def('buttonStyle', S.literal('filled', 'outline'), 'filled'),
	def('choiceStyle', S.literal('list', 'cards', 'buttons'), 'list'),
	def('mode', S.literal('light', 'dark', 'auto'), 'auto')
]);

// --- expression AST (osp_expr.ast, lax config) ----------------------------------------------------

export const KEYWORDS = new Set(['and', 'or', 'not', 'null', 'true', 'false']);

const Expr: Schema = S.lazy(() => ExprUnion);
const kind = (k: string): Field => def('kind', S.literal(k), k);
const QuestionId = S.str({
	pattern: IDENT_PATTERN,
	after: (v) => (KEYWORDS.has(v) ? `${reprStr(v)} is a reserved word and cannot be a question id` : null)
});
const Ref = S.model('Ref', [kind('ref'), req('id', QuestionId)]);
const binary = (name: string, k: string, ops: string[]): ModelSchema =>
	S.model(name, [kind(k), req('op', S.literal(...ops)), req('left', Expr), req('right', Expr)]);
const nary = (name: string, k: string): ModelSchema => S.model(name, [kind(k), req('args', S.list(Expr, { min: 2, tuple: true }))]);
const ExprUnion: Schema = S.tagged('kind', [
	['int', S.model('IntLit', [kind('int'), req('value', S.int())])],
	['decimal', S.model('DecLit', [kind('decimal'), req('value', S.decimal)])],
	['text', S.model('TextLit', [kind('text'), req('value', S.str())])],
	['bool', S.model('BoolLit', [kind('bool'), req('value', S.bool)])],
	['null', S.model('NullLit', [kind('null')])],
	['ref', Ref],
	['compare', binary('Compare', 'compare', ['==', '!=', '<', '<=', '>', '>='])],
	['arith', binary('Arith', 'arith', ['+', '-', '*', '/'])],
	['and', nary('And', 'and')],
	['or', nary('Or', 'or')],
	['not', S.model('Not', [kind('not'), req('arg', Expr)])],
	['answered', S.model('Answered', [kind('answered'), req('ref', Ref)])],
	['contains', S.model('Contains', [kind('contains'), req('ref', Ref), req('value', Expr)])],
	['if', S.model('If', [kind('if'), req('cond', Expr), req('then', Expr), { name: 'else_', alias: 'else', schema: Expr }])]
]);
export const ExprAdapter: Schema = ExprUnion;

// --- model field lists (`model_fields`, by alias) --------------------------------------------------

const QUESTION_BASE = ['id', 'label', 'help', 'showIf', 'custom', 'source'];
const ANSWERABLE = [...QUESTION_BASE, 'name', 'required', 'constraint', 'constraintMessage'];
const CHOICE_Q = [...ANSWERABLE, 'choiceList', 'choices', 'choiceOrder'];

export interface ModelInfo {
	name: string;
	fields: string[];
}

export const QUESTION_CLASSES: Record<string, ModelInfo> = {
	integer: { name: 'IntegerQuestion', fields: [...ANSWERABLE, 'type', 'min', 'max'] },
	decimal: { name: 'DecimalQuestion', fields: [...ANSWERABLE, 'type', 'min', 'max'] },
	text: { name: 'TextQuestion', fields: [...ANSWERABLE, 'type', 'multiline'] },
	single: { name: 'SingleQuestion', fields: [...CHOICE_Q, 'type'] },
	multi: { name: 'MultiQuestion', fields: [...CHOICE_Q, 'type'] },
	date: { name: 'DateQuestion', fields: [...ANSWERABLE, 'type'] },
	matrix: { name: 'MatrixQuestion', fields: [...QUESTION_BASE, 'type', 'name', 'required', 'rows', 'choiceList', 'choices'] },
	slider: {
		name: 'SliderQuestion',
		fields: [...ANSWERABLE, 'type', 'valueType', 'min', 'max', 'step', 'minLabel', 'maxLabel']
	},
	note: { name: 'NoteQuestion', fields: [...QUESTION_BASE, 'type'] }
};
export const NODE_CLASSES: Record<string, ModelInfo> = {
	block: { name: 'BlockNode', fields: ['type', 'id', 'block'] },
	branch: { name: 'BranchNode', fields: ['type', 'id', 'if', 'then', 'else'] },
	randomiser: { name: 'RandomiserNode', fields: ['type', 'id', 'children', 'pick'] },
	assign: { name: 'AssignNode', fields: ['type', 'id', 'variables'] },
	quotaCheck: { name: 'QuotaCheckNode', fields: ['type', 'id', 'quota'] },
	end: { name: 'EndNode', fields: ['type', 'id', 'outcome', 'message'] }
};
export const VARIABLE_CLASSES: Record<string, ModelInfo> = {
	embedded: { name: 'EmbeddedVariable', fields: ['id', 'name', 'kind', 'valueType', 'source', 'param', 'default'] },
	assigned: { name: 'AssignedVariable', fields: ['id', 'name', 'kind', 'levels'] },
	computed: { name: 'ComputedVariable', fields: ['id', 'name', 'kind', 'expr'] }
};
export const FIXED_CLASSES: Record<string, ModelInfo> = {
	page: { name: 'Page', fields: ['id', 'title', 'showIf', 'items', 'itemOrder', 'source'] },
	block: { name: 'Block', fields: ['id', 'title', 'pages', 'source'] },
	choiceList: { name: 'ChoiceList', fields: ['id', 'choices'] },
	quota: { name: 'Quota', fields: ['id', 'when', 'limit', 'countOn', 'onFull'] }
};
export const METADATA: ModelInfo = {
	name: 'Metadata',
	fields: ['title', 'description', 'languages', 'defaultLanguage', 'license', 'ddi', 'instruments']
};
export const SETTINGS: ModelInfo = {
	name: 'Settings',
	fields: ['backNavigation', 'saveMode', 'localCopy', 'resumeExpiryDays', 'retention', 'theme', 'endings', 'redirectTemplates']
};
/** The variant families (`property_ops.family_fields`). */
export const FAMILIES = [QUESTION_CLASSES, NODE_CLASSES, VARIABLE_CLASSES];

export const FLOW_NODE_TYPES = ['block', 'branch', 'randomiser', 'assign', 'quotaCheck', 'externalTask', 'end'];
export const MAX_CUSTOM_PROPERTIES = 40;
