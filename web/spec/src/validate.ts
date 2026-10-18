/**
 * The semantic validator (python/osp-spec/src/osp_spec/validate.py), line for line:
 * `validate(anything)` returns the diagnostics Python returns, in the same order, and never
 * throws. Stage 1 (structure) is the pydantic model (`model.ts`); stage 2 the checks below.
 * The module docstring of validate.py explains the reference-ordering rule.
 */

import { canonicalDecimal, compare, decimalOf, type Dec, isIntegral, parseDecimal, PyError, remainderIsZero, subtract } from './decimal.ts';
import { type Diagnostic, make, pointer } from './diagnostics.ts';
import { codeTests, type ExprNode, references, typecheck } from './expr.ts';
import { checkHooks, DEFAULT_PARAM_PATTERN, type HooksDoc, patternOk, placeholders, redirectProblem, type RedirectTemplate } from './hooks.ts';
import { KEYWORDS, RESERVED_EXTERNAL_PARAMS, SPEC_VERSION, Survey } from './model.ts';
import { compileFull } from './pyregex.ts';
import { hasOwn, isObject, isSpace, pyEq, pyLen, pyRepr, pySlice, pySorted, pyStrip, reprStr } from './py.ts';
import { reservedReason } from './reserved.ts';
import { charCount, checkRich, hasPipes, isTree, type Level, LIMITS, PIPE, type TextValue } from './richtext.ts';
import type { LocElem, PErr } from './schema.ts';

const IDENT = /^[A-Za-z_][A-Za-z0-9_]*$/;
const PIPE_SEARCH = new RegExp(PIPE.source);

/** Built-in `$` variables usable in piping (semantics.md §8). */
export const BUILTIN_PIPES: ReadonlySet<string> = new Set([
	'$trial',
	'$position.index',
	'$position.of',
	'$pagesDone',
	'$language',
	'$device'
]);
/** Built-ins known only once the session has ended: endings and hooks only. */
export const ENDING_PIPES: ReadonlySet<string> = new Set(['$response.id', '$session.id', '$outcome']);
const ALL_PIPES: ReadonlySet<string> = new Set([...BUILTIN_PIPES, ...ENDING_PIPES]);

/** Diagnostics for any input (a parsed JSON value). Never throws. */
export function validate(data: unknown): Diagnostic[] {
	return parse(data)[1];
}

// Parsed model objects: plain records (Python attribute names), dicts as Map.
type Obj = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

/** The parsed survey (null if structurally invalid) and its diagnostics. Never throws. */
export function parse(data: unknown): [Obj | null, Diagnostic[]] {
	try {
		return parseInner(data);
	} catch (e) {
		const name = e instanceof PyError ? e.pyName : e instanceof RangeError ? 'RecursionError' : 'Exception';
		return [null, [make('internal.error', '', `validator failed: ${name}`)]];
	}
}

function parseInner(data: unknown): [Obj | null, Diagnostic[]] {
	if (isObject(data) && hasOwn(data, 'specVersion')) {
		const version = data.specVersion;
		if (typeof version === 'string' && version !== SPEC_VERSION) {
			const msg = `unsupported specVersion ${reprStr(pySlice(version, 40))}; expected ${reprStr(SPEC_VERSION)}`;
			return [null, [make('spec.unsupported_version', '/specVersion', msg)]];
		}
	}
	const r = Survey.run(data);
	if (!r.ok) return [null, schemaDiagnostics(r.errors, data)];
	const survey = r.value as Obj;
	return [survey, new Checker(survey).run()];
}

// --- Stage 1: pydantic errors -> diagnostics ----------------------------------------------

const TYPE_CODES: Record<string, string> = {
	missing: 'schema.missing',
	union_tag_not_found: 'schema.missing',
	extra_forbidden: 'schema.extra',
	literal_error: 'schema.enum',
	union_tag_invalid: 'schema.enum',
	string_pattern_mismatch: 'schema.pattern'
};

function schemaCode(kind: string): string {
	if (hasOwn(TYPE_CODES, kind)) return TYPE_CODES[kind]!;
	if (kind.endsWith('_type') || kind === 'model_attributes_type' || kind === 'is_instance_of') return 'schema.type';
	return 'schema.value';
}

function schemaDiagnostics(errors: PErr[], data: unknown): Diagnostic[] {
	const out: Diagnostic[] = [];
	const seen = new Set<string>();
	for (const e of errors) {
		const code = schemaCode(e.type);
		const parts = locToParts(e.loc, data, e.type === 'missing' || e.type === 'extra_forbidden');
		if (e.type === 'union_tag_not_found' || e.type === 'union_tag_invalid') {
			parts.push((e.discriminator ?? 'type').replace(/^['"]+|['"]+$/g, ''));
		}
		const ptr = pointer(...parts);
		const key = code + '\u0000' + ptr;
		if (seen.has(key)) continue;
		seen.add(key);
		out.push(make(code, ptr, e.msg));
	}
	return out;
}

/** Map a pydantic `loc` onto the input, dropping union tags and member labels. */
function locToParts(loc: LocElem[], data: unknown, keepLast: boolean): Array<string | number> {
	const parts: Array<string | number> = [];
	let cur: unknown = data;
	loc.forEach((elem, i) => {
		const last = i === loc.length - 1;
		if (isObject(cur)) {
			const o = cur;
			const inCur = typeof elem === 'string' && hasOwn(o, elem);
			if ((pyEq(elem, hasOwn(o, 'type') ? o.type : null) || pyEq(elem, hasOwn(o, 'kind') ? o.kind : null)) && !(last && inCur)) {
				return; // discriminated-union tag
			}
			if (inCur) {
				parts.push(elem);
				cur = o[elem as string];
				return;
			}
		} else if (Array.isArray(cur) && typeof elem === 'number' && elem >= 0 && elem < cur.length) {
			parts.push(elem);
			cur = cur[elem];
			return;
		}
		if (last && keepLast) parts.push(elem);
	});
	return parts;
}

// --- Stage 2: semantic checks --------------------------------------------------------------

type PathElem = [string, string, number];

interface QInfo {
	q: Obj;
	ptr: string;
	page: string;
	pos: number | null;
	path: PathElem[];
}

interface VInfo {
	v: Obj;
	ptr: string;
	pos: number | null;
	path: PathElem[];
}

interface Site {
	ptr: string;
	refs: string[];
	pos: number | null;
	path: PathElem[];
	selfId: string | null;
	allowSelf: boolean;
	page: string | null;
}

function site(ptr: string, refs: string[], pos: number | null, path: PathElem[] = [], selfId: string | null = null, allowSelf = false, page: string | null = null): Site {
	return { ptr, refs, pos, path, selfId, allowSelf, page };
}

const isNoteOrMatrix = (q: Obj): boolean => q.type === 'note' || q.type === 'matrix';
const isChoice = (q: Obj): boolean => q.type === 'single' || q.type === 'multi';
const elemEq = (a: PathElem, b: PathElem): boolean => a[0] === b[0] && a[1] === b[1] && a[2] === b[2];

function textItems(text: TextValue, ptr: string): Array<[string | Obj, string]> {
	if (typeof text === 'string' || isTree(text)) return [[text, ptr]];
	return Array.from(text, ([k, v]) => [v, ptr + pointer(k)]);
}

class Checker {
	out: Diagnostic[] = [];
	questions = new Map<string, QInfo>();
	variables = new Map<string, VInfo>();
	blocks = new Map<string, number>();
	choiceLists = new Map<string, number>();
	quotas = new Map<string, number>();
	placedBlocks = new Set<string>();
	usedLists = new Set<string>();
	usedQuotas = new Set<string>();
	sites: Site[] = [];
	rowOf = new Map<string, string>();
	codeSites: Array<[ExprNode, string]> = [];
	counter = 0;
	cpos = new Map<string, number | null>();
	env: Map<string, string> | null = null;

	constructor(readonly s: Obj) {}

	emit(code: string, ptr: string, message: string): void {
		this.out.push(make(code, ptr, message));
	}

	private readonly emitFn = (code: string, ptr: string, message: string): void => this.emit(code, ptr, message);

	run(): Diagnostic[] {
		this.index();
		this.languages();
		this.names();
		this.choices();
		this.variablesCheck();
		this.quotasStatic();
		this.flow();
		this.unplaced();
		this.redirectTemplatesCheck();
		this.endings();
		this.computedCycles();
		this.referencesCheck();
		this.samePageCycles();
		this.settings();
		this.consent();
		this.choiceCodes();
		this.hooks();
		const unique = new Map<string, Diagnostic>();
		for (const d of this.out) {
			const key = `${d.code}\u0000${d.pointer}\u0000${d.message}`;
			if (!unique.has(key)) unique.set(key, d);
		}
		return [...unique.values()];
	}

	// -- index and identity ---------------------------------------------------------

	index(): void {
		const seen = new Set<string>();
		const claim = (id: string, ptr: string): boolean => {
			if (seen.has(id)) {
				this.emit('id.duplicate', ptr + '/id', `id '${id}' is already used`);
				return false;
			}
			seen.add(id);
			if (KEYWORDS.has(id)) {
				this.emit('id.reserved', ptr + '/id', `'${id}' is an expression keyword, so conditions could not refer to it`);
			}
			return true;
		};
		(this.s.choiceLists as Obj[]).forEach((cl, i) => {
			if (claim(cl.id, pointer('choiceLists', i))) this.choiceLists.set(cl.id, i);
		});
		(this.s.blocks as Obj[]).forEach((b, i) => {
			const bp = pointer('blocks', i);
			if (claim(b.id, bp)) this.blocks.set(b.id, i);
			(b.pages as Obj[]).forEach((page, j) => {
				const pp = bp + pointer('pages', j);
				claim(page.id, pp);
				(page.items as Obj[]).forEach((q, k) => {
					const qp = pp + pointer('items', k);
					if (claim(q.id, qp)) {
						this.questions.set(q.id, { q, ptr: qp, page: page.id, pos: null, path: [] });
						if (q.type === 'matrix') this.matrixRows(q, qp, page.id, claim);
					}
				});
			});
		});
		(this.s.variables as Obj[]).forEach((v, i) => {
			const vp = pointer('variables', i);
			if (claim(v.id, vp)) this.variables.set(v.id, { v, ptr: vp, pos: null, path: [] });
		});
		(this.s.quotas as Obj[]).forEach((quota, i) => {
			if (claim(quota.id, pointer('quotas', i))) this.quotas.set(quota.id, i);
		});
		const nodes = (ns: Obj[], ptr: string): void => {
			ns.forEach((n, i) => {
				const np = ptr + pointer(i);
				claim(n.id, np);
				if (n.type === 'branch') {
					nodes(n.then, np + '/then');
					nodes(n.else_, np + '/else');
				} else if (n.type === 'randomiser') nodes(n.children, np + '/children');
			});
		};
		nodes(this.s.flow, '/flow');
	}

	matrixRows(m: Obj, ptr: string, page: string, claim: (id: string, ptr: string) => boolean): void {
		const local = new Set<string>();
		(m.rows as Obj[]).forEach((row, k) => {
			const rp = ptr + pointer('rows', k);
			if (local.has(row.id)) {
				this.emit('matrix.duplicate_row', rp + '/id', `row id '${row.id}' is repeated`);
				return;
			}
			local.add(row.id);
			const rid = `${m.id}_${row.id}`;
			const rname = `${m.name ?? m.id}_${row.id}`;
			if (pyLen(rid) > 64 || pyLen(rname) > 64) {
				this.emit('matrix.row_id', rp + '/id', `the row variable '${pySlice(rid, 70)}' is longer than 64 characters`);
				return;
			}
			if (!claim(rid, rp)) return;
			const synthetic: Obj = {
				id: rid,
				type: 'single',
				label: row.label,
				help: null,
				showIf: null,
				name: rname,
				required: row.required === null ? m.required : row.required,
				constraint: null,
				constraintMessage: null,
				choiceList: m.choiceList,
				choices: m.choices,
				choiceOrder: 'fixed'
			};
			this.questions.set(rid, { q: synthetic, ptr: rp, page, pos: null, path: [] });
			this.rowOf.set(rid, m.id);
		});
	}

	names(): void {
		const named: Array<[string, string]> = [];
		for (const [qid, info] of this.questions) {
			if (this.rowOf.has(qid)) named.push([info.q.name || qid, info.ptr + '/id']);
			else if (!isNoteOrMatrix(info.q)) {
				const explicit = info.q.name !== null;
				named.push([info.q.name || info.q.id, info.ptr + (explicit ? '/name' : '/id')]);
			}
		}
		for (const vi of this.variables.values()) {
			const explicit = vi.v.name !== null;
			named.push([vi.v.name || vi.v.id, vi.ptr + (explicit ? '/name' : '/id')]);
		}
		const exact = new Map<string, string>();
		const folded = new Map<string, string>();
		for (const [name, ptr] of named) {
			const reason = reservedReason(name);
			if (reason) this.emit('name.reserved', ptr, `variable name '${name}' is reserved: ${reason}`);
			const low = name.toLowerCase();
			if (exact.has(name)) this.emit('name.duplicate', ptr, `variable name '${name}' is already used`);
			else if (folded.has(low)) {
				const other = folded.get(low)!;
				this.emit(
					'name.case_collision',
					ptr,
					`variable name '${name}' differs from '${other}' only in case; SPSS, Stata and LimeSurvey would treat them as one variable`
				);
			}
			if (!exact.has(name)) exact.set(name, ptr);
			if (!folded.has(low)) folded.set(low, name);
		}
	}

	languages(): void {
		const md = this.s.metadata;
		const seen = new Set<string>();
		(md.languages as string[]).forEach((lang, i) => {
			if (seen.has(lang)) this.emit('lang.duplicate', pointer('metadata', 'languages', i), `'${lang}' twice`);
			seen.add(lang);
		});
		if (md.defaultLanguage !== null && !seen.has(md.defaultLanguage)) {
			this.emit(
				'lang.unknown_default',
				'/metadata/defaultLanguage',
				`defaultLanguage '${md.defaultLanguage}' is not in metadata.languages`
			);
		}
		this.text(md.title, '/metadata/title', null);
		if (md.description !== null) this.text(md.description, '/metadata/description', null, BUILTIN_PIPES, 'block');
	}

	// -- text and piping ------------------------------------------------------------

	text(text: TextValue, ptr: string, base: Site | null, builtins: ReadonlySet<string> = BUILTIN_PIPES, level: Level | null = null): string[] {
		const langs = this.s.metadata.languages as string[];
		const values = textItems(text, ptr);
		if (text instanceof Map) {
			for (const k of text.keys()) {
				if (!langs.includes(k)) this.emit('text.unknown_language', ptr + pointer(k), `language '${k}' is not in metadata.languages`);
			}
			const missing = langs.filter((lang) => !text.has(lang));
			if (missing.length) this.emit('text.missing_translation', ptr, `no text for: ${missing.join(', ')}`);
		}
		const piped: string[] = [];
		for (const [v, vp] of values) {
			let pipes: Array<[string, string]>;
			if (typeof v === 'string') pipes = Array.from(v.matchAll(PIPE), (m) => [vp, m[1]!]);
			else pipes = checkRich(v as never, level ?? 'block', vp, this.emitFn);
			if (level !== null) {
				const n = charCount(v as never);
				if (n > LIMITS[level]) this.emit('text.too_long', vp, `${n} characters; this field allows at most ${LIMITS[level]}`);
			}
			const bySite = new Map<string, string[]>();
			for (const [pp, raw] of pipes) {
				const inner = pyStrip(raw);
				if (IDENT.test(inner)) {
					if (!bySite.has(pp)) bySite.set(pp, []);
					bySite.get(pp)!.push(inner);
				} else if (builtins.has(inner)) continue;
				else this.emit('pipe.invalid', pp, `'\${${raw}}' is not a valid reference`);
			}
			for (const [pp, refs] of bySite) {
				const b = base ?? site(pp, [], null);
				this.sites.push(site(pp, refs, b.pos, b.path, b.selfId, false, b.page));
				piped.push(...refs);
			}
		}
		return piped;
	}

	// -- choices --------------------------------------------------------------------

	choices(): void {
		(this.s.choiceLists as Obj[]).forEach((cl, i) => this.choiceItems(cl.choices, pointer('choiceLists', i, 'choices'), null));
		for (const [qid, info] of this.questions) {
			const q = info.q;
			if (this.rowOf.has(qid) || !(isChoice(q) || q.type === 'matrix')) continue;
			if ((q.choiceList === null) === (q.choices === null)) {
				this.emit('choice.source', info.ptr, `question '${q.id}' needs exactly one of 'choiceList' or 'choices'`);
			}
			if (q.choiceList !== null) {
				this.usedLists.add(q.choiceList);
				if (!this.choiceLists.has(q.choiceList)) {
					this.emit('ref.unknown_choice_list', info.ptr + '/choiceList', `no choice list with id '${q.choiceList}'`);
				}
			}
		}
		for (const [cid, i] of this.choiceLists) {
			if (!this.usedLists.has(cid)) this.emit('choicelist.unused', pointer('choiceLists', i), `'${cid}' is unused`);
		}
	}

	choiceItems(choices: Obj[], ptr: string, base: Site | null): void {
		const seen = new Set<string>();
		const types = new Set<string>();
		choices.forEach((c, k) => {
			const cp = ptr + pointer(k);
			const key = String(c.value);
			types.add(typeof c.value);
			if (typeof c.value === 'string' && (!c.value || Array.from(c.value as string).some(isSpace))) {
				this.emit(
					'choice.invalid_value',
					cp + '/value',
					'choice codes must be non-empty and contain no whitespace (XForms stores multi answers space-separated)'
				);
			}
			if (seen.has(key)) this.emit('choice.duplicate_value', cp + '/value', `code ${reprStr(key)} is repeated`);
			seen.add(key);
			this.text(c.label, cp + '/label', base, BUILTIN_PIPES, 'inline');
		});
		if (types.size > 1) this.emit('choice.mixed_types', ptr, 'list mixes integer and text codes');
	}

	// -- variables and quotas -------------------------------------------------------

	variablesCheck(): void {
		for (const vi of this.variables.values()) {
			const v = vi.v;
			if (v.kind === 'assigned') {
				const seen = new Set<string>();
				(v.levels as Array<string | number>).forEach((level, k) => {
					if (seen.has(String(level))) {
						this.emit('variable.duplicate_level', vi.ptr + pointer('levels', k), `level ${pyRepr(level)} is repeated`);
					}
					seen.add(String(level));
				});
			} else if (v.kind === 'embedded' && v.default !== null) {
				if (!defaultFits(v.valueType, v.default)) {
					this.emit('variable.default_type', vi.ptr + '/default', `default ${pyRepr(v.default)} is not a valid ${v.valueType}`);
				}
			}
		}
	}

	quotasStatic(): void {
		(this.s.quotas as Obj[]).forEach((quota, i) => {
			const blk = quota.onFull.block;
			if (blk !== null && !this.blocks.has(blk)) {
				this.emit('ref.unknown_block', pointer('quotas', i, 'onFull', 'block'), `no block with id '${blk}'`);
			}
		});
	}

	// -- flow -----------------------------------------------------------------------

	flow(): void {
		if (!this.s.flow.length) this.emit('flow.empty', '/flow', 'flow is empty; no block will be shown');
		this.walk(this.s.flow, '/flow', []);
		for (const [bid, i] of this.blocks) {
			if (!this.placedBlocks.has(bid)) this.emit('block.unused', pointer('blocks', i), `block '${bid}' is not in flow`);
		}
		for (const [qid, i] of this.quotas) {
			if (!this.usedQuotas.has(qid)) {
				this.emit('quota.unused', pointer('quotas', i), `quota '${qid}' is never checked`);
				const when = this.s.quotas[i].when as ExprNode;
				this.sites.push(site(pointer('quotas', i, 'when'), references(when), null));
			}
		}
		for (const vi of this.variables.values()) {
			if (vi.v.kind === 'assigned' && vi.pos === null) {
				this.emit('variable.never_assigned', vi.ptr, `no assign node sets '${vi.v.id}'; it will always be null`);
			}
		}
	}

	walk(nodes: Obj[], ptr: string, path: PathElem[]): boolean {
		let terminated = false;
		let flagged = false;
		nodes.forEach((node, i) => {
			const np = ptr + pointer(i);
			if (terminated && !flagged) {
				this.emit('flow.unreachable', np, 'an earlier node always ends the survey');
				flagged = true;
			}
			terminated = this.node(node, np, path) || terminated;
		});
		return terminated;
	}

	node(node: Obj, ptr: string, path: PathElem[]): boolean {
		switch (node.type) {
			case 'block':
				this.placeBlock(node.block, ptr + '/block', path);
				return false;
			case 'branch': {
				this.exprSite(node.if_, ptr + '/if', this.counter, path, true);
				if (!node.then.length) this.emit('flow.empty_branch', ptr + '/then', "branch has no 'then' nodes");
				const t = this.walk(node.then, ptr + '/then', [...path, ['branch', node.id, 0]]);
				const e = this.walk(node.else_, ptr + '/else', [...path, ['branch', node.id, 1]]);
				return t && e && node.else_.length > 0;
			}
			case 'randomiser': {
				if (node.pick !== null && node.pick > node.children.length) {
					this.emit('flow.pick_too_large', ptr + '/pick', `pick ${node.pick} but only ${node.children.length} children`);
				}
				const ends = (node.children as Obj[]).map((c, k) =>
					this.node(c, ptr + pointer('children', k), [...path, ['randomiser', node.id, k]])
				);
				return node.pick === null ? ends.some(Boolean) : ends.every(Boolean);
			}
			case 'assign':
				(node.variables as string[]).forEach((vid, k) => {
					const vp = ptr + pointer('variables', k);
					const vi = this.variables.get(vid);
					if (vi === undefined) this.emit('ref.unknown_variable', vp, `no variable with id '${vid}'`);
					else if (vi.v.kind !== 'assigned') {
						this.emit('flow.assign_wrong_kind', vp, `'${vid}' is ${vi.v.kind}; only 'assigned' variables can be assigned`);
					} else if (vi.pos !== null) this.emit('flow.variable_reassigned', vp, `'${vid}' is already assigned`);
					else {
						vi.pos = this.counter;
						vi.path = path;
						this.counter += 1;
					}
				});
				return false;
			case 'quotaCheck': {
				const i = this.quotas.get(node.quota);
				if (i === undefined) {
					this.emit('ref.unknown_quota', ptr + '/quota', `no quota '${node.quota}'`);
					return false;
				}
				const quota = this.s.quotas[i];
				const first = !this.usedQuotas.has(node.quota);
				this.usedQuotas.add(node.quota);
				this.exprSite(quota.when, pointer('quotas', i, 'when'), this.counter, path, true);
				const blk = quota.onFull.block;
				if (first && blk !== null && this.blocks.has(blk)) {
					this.placeBlock(blk, pointer('quotas', i, 'onFull', 'block'), [...path, ['quota', node.id, 1]]);
				}
				return false;
			}
			case 'externalTask':
				this.externalNode(node, ptr, path);
				return false;
		}
		// end
		if (node.message !== null) this.text(node.message, ptr + '/message', site(ptr, [], this.counter, path), BUILTIN_PIPES, 'block');
		return true;
	}

	/** A literal (unpiped) param of an end redirect or an external task, checked against its
	 * pattern. False for a piped value, which the caller checks as text. */
	literalParam(value: string, vptr: string, t: RedirectTemplate, name: string, code: string, never: string, refused: string): boolean {
		if (PIPE_SEARCH.test(value)) return false;
		const declared = t.params.get(name);
		const pattern = (declared !== undefined ? declared.pattern : null) || DEFAULT_PARAM_PATTERN;
		const re = patternOk(pattern) ? compileFull(pattern) : null;
		if (re !== null && !re.test(value)) {
			this.emit(code, vptr, `'${pySlice(value, 40)}' does not match the pattern ${reprStr(pattern)}, ${never}`);
		} else if (value === '.' || value === '..') {
			this.emit(code, vptr, `'${value}' would be read as a path segment, ${refused}`);
		}
		return true;
	}

	externalNode(node: Obj, ptr: string, path: PathElem[]): void {
		const templates = redirectTemplates(this.s);
		const t = templates.get(node.template);
		if (t === undefined) {
			this.emit(
				'external.unknown_template',
				ptr + '/template',
				`no redirect template '${node.template}' in settings.redirectTemplates (or hooks.redirects)`
			);
		} else {
			const names = placeholders(t.url);
			const reserved = names.filter((n) => RESERVED_EXTERNAL_PARAMS.includes(n));
			if (reserved.length) {
				this.emit(
					'external.reserved_param',
					ptr + '/template',
					`the template reserves ${pySorted(RESERVED_EXTERNAL_PARAMS).join(', ')} for the platform; rename the placeholder(s): ${reserved.join(', ')}`
				);
			}
			const params = node.params as Map<string, string>;
			if (!sameSorted([...params.keys()], names)) {
				this.emit('external.params', ptr + '/params', `the template's placeholders are: ${names.join(', ') || 'none'}; give exactly those`);
			}
			for (const [name, value] of params) {
				const vptr = ptr + pointer('params', name);
				if (
					this.literalParam(value, vptr, t, name, 'external.param_literal', 'so the external task would never be reached', 'so it is refused')
				) {
					continue;
				}
				const refs = this.text(value, vptr, site(ptr, [], this.counter, path), ALL_PIPES);
				for (const ref of refs) {
					if (this.questions.has(ref) && !this.variables.has(ref)) {
						this.emit(
							'external.param_question',
							vptr,
							`'${ref}' is an answer: it is sent to the external task (a data export the owner confirms; listed in the codebook)`
						);
						break;
					}
				}
			}
		}
		(node.returns as string[]).forEach((vid, k) => {
			const vi = this.variables.get(vid);
			if (vi === undefined || vi.v.kind !== 'embedded') {
				this.emit(
					'external.return_target',
					ptr + pointer('returns', k),
					`'${vid}' is not an embedded variable; a returned value is captured like a URL parameter, so it needs an embedded variable (source: url) to store it`
				);
			}
		});
	}

	placeBlock(bid: string, ptr: string, path: PathElem[]): void {
		const bi = this.blocks.get(bid);
		if (bi === undefined) {
			this.emit('ref.unknown_block', ptr, `no block with id '${bid}'`);
			return;
		}
		if (this.placedBlocks.has(bid)) {
			this.emit('flow.block_reused', ptr, `block '${bid}' is already in the flow; a block may appear once`);
			return;
		}
		this.placedBlocks.add(bid);
		const bp = pointer('blocks', bi);
		(this.s.blocks[bi].pages as Obj[]).forEach((page, j) => {
			const pp = bp + pointer('pages', j);
			if (page.title !== null) this.text(page.title, pp + '/title', site(pp, [], this.counter, path), BUILTIN_PIPES, 'inline');
			if (page.showIf !== null) this.exprSite(page.showIf, pp + '/showIf', this.counter, path, true);
			for (const q of page.items as Obj[]) {
				const info = this.questions.get(q.id);
				if (info === undefined || info.q !== q) continue; // duplicate id, already reported
				info.pos = this.counter;
				info.path = path;
				this.counter += 1;
				this.questionSites(info);
				if (q.type === 'matrix') {
					for (const rid of this.rowsOf(q.id)) {
						const r = this.questions.get(rid)!;
						r.pos = info.pos;
						r.path = path;
					}
				}
			}
		});
	}

	unplaced(): void {
		for (const [bid, i] of this.blocks) {
			if (this.placedBlocks.has(bid)) continue;
			(this.s.blocks[i].pages as Obj[]).forEach((page, j) => {
				if (page.title !== null) this.text(page.title, pointer('blocks', i, 'pages', j, 'title'), null, BUILTIN_PIPES, 'inline');
				if (page.showIf !== null) this.exprSite(page.showIf, pointer('blocks', i, 'pages', j, 'showIf'), null, [], true);
			});
		}
		for (const [qid, info] of this.questions) {
			if (info.pos === null && !this.rowOf.has(qid)) this.questionSites(info);
		}
	}

	rowsOf(matrixId: string): string[] {
		return [...this.rowOf].filter(([, mid]) => mid === matrixId).map(([rid]) => rid);
	}

	questionSites(info: QInfo): void {
		const q = info.q;
		const base = site(info.ptr, [], info.pos, info.path, q.id, false, info.page);
		if (q.showIf !== null) this.exprSite(q.showIf, info.ptr + '/showIf', info.pos, info.path, true, q.id, false, info.page);
		if (!isNoteOrMatrix(q) && q.constraint !== null) {
			this.exprSite(q.constraint, info.ptr + '/constraint', info.pos, info.path, true, q.id, true, info.page);
		}
		if (q.type === 'integer' || q.type === 'decimal') this.bounds(q, info.ptr);
		if (q.type === 'slider') {
			this.slider(q, info.ptr);
			for (const key of ['minLabel', 'maxLabel']) {
				if (q[key] !== null) this.text(q[key], info.ptr + '/' + key, base, BUILTIN_PIPES, 'inline');
			}
		}
		if (q.type === 'matrix') {
			(q.rows as Obj[]).forEach((row, k) => {
				this.text(row.label, info.ptr + pointer('rows', k, 'label'), base, BUILTIN_PIPES, 'inline');
			});
			if (q.choices !== null) this.choiceItems(q.choices, info.ptr + '/choices', base);
		}
		this.text(q.label, info.ptr + '/label', base, BUILTIN_PIPES, q.type === 'note' ? 'block' : 'stem');
		if (q.help !== null) this.text(q.help, info.ptr + '/help', base, BUILTIN_PIPES, 'stem');
		if (!isNoteOrMatrix(q) && q.constraintMessage !== null) {
			this.text(q.constraintMessage, info.ptr + '/constraintMessage', base, BUILTIN_PIPES, 'inline');
		}
		if (isChoice(q) && q.choices !== null) this.choiceItems(q.choices, info.ptr + '/choices', base);
	}

	exprSite(e: ExprNode, ptr: string, pos: number | null, path: PathElem[], boolean: boolean, selfId: string | null = null, allowSelf = false, page: string | null = null): void {
		this.sites.push(site(ptr, references(e), pos, path, selfId, allowSelf, page));
		this.typecheck(e, ptr, boolean);
		this.codeSites.push([e, ptr]);
	}

	typecheck(e: ExprNode, ptr: string, boolean: boolean): void {
		for (const [suffix, message] of typecheck(e, this.typeEnv(), boolean)) this.emit('expr.type', ptr + suffix, message);
	}

	typeEnv(): Map<string, string> {
		if (this.env === null) {
			const env = new Map<string, string>();
			for (const [qid, i] of this.questions) {
				if (!isNoteOrMatrix(i.q)) env.set(qid, i.q.type === 'slider' ? i.q.valueType : i.q.type);
			}
			for (const [vid, vi] of this.variables) {
				if (vi.v.kind === 'embedded') env.set(vid, vi.v.valueType);
				else if (vi.v.kind === 'assigned') env.set(vid, 'single');
			}
			this.env = env;
		}
		return this.env;
	}

	// -- computed variables and references ------------------------------------------

	choiceCodes(): void {
		for (const [e, ptr] of this.codeSites) {
			for (const [suffix, ref, code] of codeTests(e)) {
				const codes = this.codesOf(ref);
				if (codes !== null && !codes.has(String(code))) {
					this.emit(
						'ref.unknown_choice_code',
						ptr + suffix,
						`${pyRepr(code)} is not a choice code of '${ref}' (codes: ${pySorted(codes).join(', ')}); the test is always false`
					);
				}
			}
		}
	}

	codesOf(ref: string): Set<string> | null {
		const info = this.questions.get(ref);
		if (info !== undefined) {
			const q = info.q;
			if (!isChoice(q)) return null;
			let choices: Obj[] | null = q.choices;
			if (choices === null && q.choiceList !== null) {
				const i = this.choiceLists.get(q.choiceList);
				choices = i !== undefined ? this.s.choiceLists[i].choices : null;
			}
			return choices === null ? null : new Set(choices.map((c) => String(c.value)));
		}
		const vi = this.variables.get(ref);
		if (vi !== undefined && vi.v.kind === 'assigned') return new Set((vi.v.levels as unknown[]).map(String));
		return null;
	}

	computedCycles(): void {
		const state = new Map<string, number>(); // 1 visiting, 2 done
		const visit = (vid: string): void => {
			state.set(vid, 1);
			const vi = this.variables.get(vid)!;
			for (const ref of references(vi.v.expr)) {
				const target = this.variables.get(ref);
				if (target === undefined || target.v.kind !== 'computed') continue;
				if (state.get(ref) === 1) {
					this.emit('variable.cycle', vi.ptr + '/expr', `computed variable '${vid}' depends on itself via '${ref}'`);
					this.cpos.set(vid, null);
				} else if (!state.has(ref)) visit(ref);
			}
			state.set(vid, 2);
		};
		for (const [vid, vi] of this.variables) {
			if (vi.v.kind === 'computed' && !state.has(vid)) visit(vid);
			if (vi.v.kind === 'computed') {
				this.sites.push(site(vi.ptr + '/expr', references(vi.v.expr), null));
				this.typecheck(vi.v.expr, vi.ptr + '/expr', false);
				this.codeSites.push([vi.v.expr, vi.ptr + '/expr']);
			}
		}
	}

	computedPos(vid: string, stack: ReadonlySet<string> = new Set()): number | null {
		if (this.cpos.has(vid)) return this.cpos.get(vid)!;
		const vi = this.variables.get(vid)!;
		let latest = -1;
		const inner = new Set(stack).add(vid);
		for (const ref of references(vi.v.expr)) {
			const t = this.targetPos(ref, inner);
			if (t === null) continue;
			latest = Math.max(latest, t);
		}
		this.cpos.set(vid, latest);
		return latest;
	}

	targetPos(ref: string, stack: ReadonlySet<string>): number | null {
		const info = this.questions.get(ref);
		if (info !== undefined) return info.pos;
		const vi = this.variables.get(ref);
		if (vi === undefined) return null;
		if (vi.v.kind === 'embedded') return -1;
		if (vi.v.kind === 'assigned') return vi.pos;
		if (stack.has(ref)) return null;
		return this.computedPos(ref, stack);
	}

	referencesCheck(): void {
		for (const s of this.sites) for (const ref of s.refs) this.checkRef(s, ref);
	}

	checkRef(s: Site, ref: string): void {
		let t: number | null;
		let tpath: PathElem[] | null = null;
		const info = this.questions.get(ref);
		if (info !== undefined) {
			if (info.q.type === 'note') {
				this.emit('ref.no_value', s.ptr, `'${ref}' is a note and has no value`);
				return;
			}
			if (info.q.type === 'matrix') {
				const rows = this.rowsOf(ref).slice(0, 3).join(', ');
				this.emit('ref.no_value', s.ptr, `'${ref}' is a matrix and has no value of its own; refer to a row (${rows})`);
				return;
			}
			if (info.pos === null) {
				this.emit('ref.not_in_flow', s.ptr, `'${ref}' is in a block that is not in the flow`);
				return;
			}
			t = info.pos;
			tpath = info.path;
		} else if (this.variables.has(ref)) {
			const vi = this.variables.get(ref)!;
			if (vi.v.kind === 'embedded') return;
			if (vi.v.kind === 'assigned') {
				t = vi.pos;
				tpath = vi.path;
			} else t = this.computedPos(ref);
		} else {
			this.emit('ref.unknown', s.ptr, `'${ref}' is not a question or variable id`);
			return;
		}
		if (ref === s.selfId) {
			if (!s.allowSelf) this.emit('ref.self', s.ptr, `'${ref}' refers to itself`);
			return;
		}
		if (s.pos === null || t === null) return;
		if (t >= s.pos) {
			if (s.page !== null && this.samePageOnly(ref, s)) return;
			this.emit('ref.forward', s.ptr, `'${ref}' comes later in the flow`);
			return;
		}
		if (tpath === null) return;
		const n = Math.min(s.path.length, tpath.length);
		for (let i = 0; i < n; i++) {
			const a = s.path[i]!;
			const b = tpath[i]!;
			if (elemEq(a, b)) continue;
			if (a[0] === b[0] && a[1] === b[1]) {
				if (a[0] === 'randomiser') {
					this.emit(
						'ref.randomised_sibling',
						s.ptr,
						`'${ref}' is in another child of randomiser '${a[1]}'; it may not have been shown yet`
					);
				} else {
					this.emit('ref.other_branch', s.ptr, `'${ref}' is in the other arm of branch '${a[1]}'; it is never reached on this path`);
				}
			}
			return;
		}
	}

	questionInputs(ref: string, seen: ReadonlySet<string> = new Set()): Set<string> {
		if (this.questions.has(ref)) return new Set([ref]);
		const vi = this.variables.get(ref);
		if (vi === undefined || vi.v.kind !== 'computed' || seen.has(ref)) return new Set();
		const out = new Set<string>();
		const inner = new Set(seen).add(ref);
		for (const r of references(vi.v.expr)) for (const x of this.questionInputs(r, inner)) out.add(x);
		return out;
	}

	samePageOnly(ref: string, s: Site): boolean {
		for (const qid of this.questionInputs(ref)) {
			const info = this.questions.get(qid)!;
			if (info.pos !== null && s.pos !== null && info.pos >= s.pos && info.page !== s.page) return false;
		}
		const vi = this.variables.get(ref);
		if (vi !== undefined && vi.v.kind === 'assigned') return false;
		return true;
	}

	samePageCycles(): void {
		const edges = new Map<string, Set<string>>();
		for (const [qid, info] of this.questions) {
			if (info.q.showIf === null) continue;
			const deps = new Set<string>();
			for (const r of references(info.q.showIf)) {
				for (const x of this.questionInputs(r)) if (this.questions.get(x)!.page === info.page) deps.add(x);
			}
			deps.delete(qid);
			edges.set(qid, deps);
		}
		const state = new Map<string, number>();
		const reported = new Set<string>();
		const visit = (q: string, stack: string[]): void => {
			state.set(q, 1);
			stack.push(q);
			for (const nxt of pySorted(edges.get(q) ?? [])) {
				if (state.get(nxt) === 1) {
					const loop = stack.slice(stack.indexOf(nxt));
					if (!loop.some((x) => reported.has(x))) {
						for (const x of loop) reported.add(x);
						const info = this.questions.get(loop[0]!)!;
						this.emit(
							'ref.cycle',
							info.ptr + '/showIf',
							'show-if conditions on one page depend on each other in a loop: ' + [...loop, loop[0]].join(' -> ')
						);
					}
				} else if (!state.has(nxt)) visit(nxt, stack);
			}
			stack.pop();
			state.set(q, 2);
		};
		for (const q of pySorted(edges.keys())) if (!state.has(q)) visit(q, []);
	}

	// -- numbers --------------------------------------------------------------------

	bounds(q: Obj, ptr: string): void {
		const values = new Map<string, Dec>();
		for (const key of ['min', 'max']) {
			const raw = q[key];
			if (raw === null) continue;
			const text = canonicalDecimal(raw);
			if (text === null) {
				this.emit('question.bounds', `${ptr}/${key}`, `${key} ${pyRepr(raw)} is not a usable number`);
				continue;
			}
			values.set(key, decimalOf(text));
		}
		const lo = values.get('min');
		const hi = values.get('max');
		if (lo !== undefined && hi !== undefined && compare(lo, hi) > 0) this.emit('question.bounds', ptr + '/min', 'min is greater than max');
	}

	slider(q: Obj, ptr: string): void {
		const values = new Map<string, Dec>();
		for (const key of ['min', 'max', 'step']) {
			const raw = q[key];
			const text = canonicalDecimal(raw);
			if (text === null) {
				this.emit('question.slider', `${ptr}/${key}`, `${key} ${pyRepr(raw)} is not a usable number`);
				continue;
			}
			const value = decimalOf(text);
			if (q.valueType === 'integer' && !isIntegral(value)) {
				this.emit('question.slider', `${ptr}/${key}`, `${key} must be a whole number on an integer slider`);
				continue;
			}
			values.set(key, value);
		}
		const step = values.get('step');
		if (step !== undefined && (step.coef === 0n || step.neg)) {
			this.emit('question.slider', ptr + '/step', 'step must be greater than 0');
			return;
		}
		const lo = values.get('min');
		const hi = values.get('max');
		if (lo !== undefined && hi !== undefined) {
			if (compare(lo, hi) >= 0) this.emit('question.slider', ptr + '/min', 'min must be less than max');
			else if (step !== undefined && !remainderIsZero(subtract(hi, lo), step)) {
				this.emit('question.slider', ptr + '/step', 'max is not min plus a whole number of steps, so the right end cannot be picked');
			}
		}
	}

	// -- settings, consent, endings, redirects, hooks --------------------------------

	settings(): void {
		const r = this.s.settings.retention;
		if (r === null) return;
		const ptr = '/settings/retention';
		if (r.kind === 'days-after-close' && (r.days === null || r.until !== null)) {
			this.emit('settings.retention', ptr, "'days-after-close' needs 'days' (and no 'until')");
		} else if (r.kind === 'after-date' && (r.until === null || r.days !== null)) {
			this.emit('settings.retention', ptr, "'after-date' needs 'until' (and no 'days')");
		} else if (r.kind === 'indefinite' && (r.days !== null || r.until !== null)) {
			this.emit('settings.retention', ptr, "'indefinite' takes no 'days' or 'until'");
		}
		if (r.until !== null && !isoDate(r.until)) this.emit('settings.retention', ptr + '/until', `${reprStr(r.until)} is not a date`);
	}

	consent(): void {
		const c = this.s.consent;
		if (c === null) return;
		for (const key of ['text', 'agreeLabel', 'declineLabel']) {
			const ptr = '/consent/' + key;
			this.text(c[key], ptr, null, BUILTIN_PIPES, key === 'text' ? 'block' : 'inline');
			if (hasPipes(c[key])) this.emit('consent.pipe', ptr, 'the consent page is shown first: nothing can be piped');
		}
		if (c.declineOutcome === 'complete') this.emit('consent.outcome', '/consent/declineOutcome', "a decline cannot end 'complete'");
	}

	endings(): void {
		const endings = this.s.settings.endings as Map<string, Obj>;
		if (!endings.size) return;
		const reached = reachedOutcomes(this.s);
		const declined = this.s.consent !== null ? this.s.consent.declineOutcome : 'declined';
		const templates = redirectTemplates(this.s);
		for (const [outcome, ending] of endings) {
			const ptr = pointer('settings', 'endings', outcome);
			if (!reached.has(outcome)) {
				this.emit(
					'ending.unreachable',
					ptr,
					`no end node, quota or consent decline ends with '${outcome}', so this ending is never shown`
				);
			}
			const base = site(ptr, [], this.counter, []);
			const texts: Array<[string, TextValue | null, Level]> = [
				['title', ending.title, 'inline'],
				['body', ending.body, 'block']
			];
			if (ending.redirect !== null) texts.push(['redirect/label', ending.redirect.label, 'inline']);
			for (const [key, text, level] of texts) {
				if (text !== null) this.text(text, ptr + '/' + key, base, ALL_PIPES, level);
			}
			if (ending.redirect !== null) this.redirect(ending.redirect, ptr + '/redirect', templates, outcome === declined);
			if (ending.summary === 'answers' && outcome === declined) {
				this.emit('ending.declined_summary', ptr + '/summary', 'a decline records no response, so there are no answers to show');
			}
		}
	}

	redirectTemplatesCheck(): void {
		const hookNames = new Set<string>(this.s.hooks !== null && this.s.hooks.redirects !== null ? this.s.hooks.redirects.keys() : []);
		for (const [name, t] of this.s.settings.redirectTemplates as Map<string, RedirectTemplate>) {
			const ptr = pointer('settings', 'redirectTemplates', name);
			const why = redirectProblem(t);
			if (why !== null) this.emit('redirect.template', ptr, `redirect template: ${why}`);
			if (hookNames.has(name)) {
				this.emit('redirect.template_clash', ptr, `'${name}' is also declared in hooks.redirects; a template has one home`);
			}
		}
	}

	redirect(r: Obj, ptr: string, templates: Map<string, RedirectTemplate>, declined: boolean): void {
		const t = templates.get(r.template);
		if (t === undefined) {
			this.emit(
				'redirect.unknown_template',
				ptr + '/template',
				`no redirect template '${r.template}' in settings.redirectTemplates (or hooks.redirects)`
			);
			return;
		}
		const names = placeholders(t.url);
		const params = r.params as Map<string, string>;
		if (!sameSorted([...params.keys()], names)) {
			this.emit('redirect.params', ptr + '/params', `the template's placeholders are: ${names.join(', ') || 'none'}; give exactly those`);
		}
		for (const [name, value] of params) {
			const vptr = ptr + pointer('params', name);
			if (this.literalParam(value, vptr, t, name, 'redirect.param_literal', 'so the redirect would never be followed', 'so the redirect is refused')) {
				continue;
			}
			const refs = this.text(value, vptr, site(ptr, [], this.counter, []), ALL_PIPES);
			if (declined && value.includes('$response.id')) {
				this.emit('redirect.params', vptr, 'a decline records no response, so ${$response.id} is empty here');
			}
			for (const ref of refs) {
				if (this.questions.has(ref) && !this.variables.has(ref)) {
					this.emit(
						'redirect.param_question',
						vptr,
						`'${ref}' is an answer: it is sent to the redirect's site (a data export the owner confirms; listed in the codebook)`
					);
					break;
				}
			}
		}
		if (r.delay === 0 && r.mode === 'auto') {
			this.emit(
				'redirect.immediate',
				ptr + '/delay',
				"with a delay of 0 participants never see this ending's text; a longer delay or link mode keeps it readable (WCAG 2.2.1)"
			);
		}
	}

	hooks(): void {
		if (this.s.hooks === null) return;
		const readable = [...this.questions].filter(([, info]) => !isNoteOrMatrix(info.q)).map(([qid]) => qid);
		readable.push(...this.variables.keys());
		checkHooks(this.s.hooks as HooksDoc, readable, [], this.emitFn);
	}
}

// --- Helpers -----------------------------------------------------------------------------------

function sameSorted(a: string[], b: string[]): boolean {
	const x = pySorted(a);
	const y = pySorted(b);
	return x.length === y.length && x.every((v, i) => v === y[i]);
}

const BUILTIN_OUTCOMES = ['complete', 'hook-failed'];

/** Every outcome a session can end with: end nodes, checked quotas' onFull, the consent
 * decline and the built-ins. */
export function reachedOutcomes(survey: Obj): Set<string> {
	const out = new Set(BUILTIN_OUTCOMES);
	const checked = new Set<string>();
	const walk = (nodes: Obj[]): void => {
		for (const n of nodes) {
			if (n.type === 'end') out.add(n.outcome);
			else if (n.type === 'quotaCheck') checked.add(n.quota);
			else if (n.type === 'branch') {
				walk(n.then);
				walk(n.else_);
			} else if (n.type === 'randomiser') walk(n.children);
		}
	};
	walk(survey.flow);
	for (const q of survey.quotas as Obj[]) if (checked.has(q.id)) out.add(q.onFull.outcome);
	if (survey.consent !== null) out.add(survey.consent.declineOutcome);
	return out;
}

/** `settings.redirectTemplates` and `hooks.redirects` as one map. */
export function redirectTemplates(survey: Obj): Map<string, RedirectTemplate> {
	const out = new Map<string, RedirectTemplate>(survey.hooks !== null && survey.hooks.redirects !== null ? survey.hooks.redirects : []);
	for (const [k, v] of survey.settings.redirectTemplates as Map<string, RedirectTemplate>) out.set(k, v);
	return out;
}

function defaultFits(valueType: string, value: string | number): boolean {
	if (valueType === 'text') return typeof value === 'string';
	if (valueType === 'integer') return typeof value === 'number';
	if (typeof value === 'number') return true;
	const p = parseDecimal(value);
	return p !== null && p.kind === 'finite';
}

const DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

/** `date.fromisoformat` succeeds on a `^\d{4}-\d{2}-\d{2}$` string. */
function isoDate(s: string): boolean {
	const m = /^([0-9]{4})-([0-9]{2})-([0-9]{2})$/.exec(s);
	if (!m) return false;
	const y = Number(m[1]);
	const mo = Number(m[2]);
	const d = Number(m[3]);
	if (y < 1 || mo < 1 || mo > 12 || d < 1) return false;
	const leap = (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
	return d <= (mo === 2 && leap ? 29 : DAYS[mo - 1]!);
}
