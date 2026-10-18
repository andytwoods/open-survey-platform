/**
 * The runtime plan compiler in TypeScript: an `osp-survey` document (raw JSON, as stored)
 * → the plan `web/engine` runs. A port of `python/osp-runtime/src/osp_runtime/plan.py`
 * (task CE3, planning/client-edits.md decision 7): the output is byte-identical to Python
 * (same canonical JSON, same checksum), checked by `test/compile-parity.test.ts` against
 * vectors Python writes (`make engine-fixtures` → `.build/plan-vectors.json`).
 *
 * Python compiles a pydantic `Survey`, so every default the model fills in is filled in here
 * the same way (`required: false`, `choiceOrder: "fixed"`, slider `0..100 step 1`, consent
 * labels, ending `status`/`summary`, redirect `delay`/`mode`, …), and every expression is
 * re-serialised as `osp_expr` would dump it (a `decimal` literal's text as Python's
 * `str(Decimal)`, an integer beyond ±(2^53 − 1) as decimal text).
 *
 * Validation is not done here. The survey must be one `osp_spec.parse` accepts; pass a
 * `validate` function (the TS validator, task CE4) to have `compileSurvey` / `compilePlan`
 * refuse what Python refuses, with its diagnostics. Without one the input is trusted, and a
 * document too broken to compile gives an `internal.error` diagnostic, never a crash.
 *
 * Known limits of byte identity (JSON parsing, not the compiler): an integer beyond 2^53
 * read by `JSON.parse` has already lost digits; an integral float (`1.0`, `1e16`) is a
 * float in Python but an integer in JS, so it serialises differently (only reachable in a
 * hook manifest's number schema or a number-valued decimal literal).
 */

import { canonicalJson, planChecksum } from './canonical.ts';
import { ENGINE_VERSION, PLAN_VERSION, type Plan } from './plan.ts';
import { sha256, toHex, utf8 } from './sha256.ts';

type Json = unknown;
type Obj = Record<string, unknown>;
export type CompiledSegment = string | { pipe: string };
export type CompiledBlock = Record<string, unknown>;

/** A validator diagnostic as `osp_spec.Diagnostic` dumps it. */
export interface PlanDiagnostic {
	severity: 'error' | 'warning' | 'info';
	code: string;
	pointer: string;
	message: string;
}

/** Validates raw survey JSON the way `osp_spec.parse` does (the TS validator, CE4). */
export type SurveyValidator = (data: unknown) => PlanDiagnostic[];

export interface CompileOptions {
	/** A hook manifest that replaces the survey's own `hooks` (carried as given). */
	hooks?: Json;
	/** Validator run first; its error diagnostics refuse the survey as Python does. */
	validate?: SurveyValidator;
}

/** The survey has error diagnostics, so no plan can be built (`osp_runtime.plan.PlanError`). */
export class PlanError extends Error {
	readonly diagnostics: PlanDiagnostic[];
	constructor(diagnostics: PlanDiagnostic[]) {
		super(`survey has ${diagnostics.length} error diagnostic(s)`);
		this.name = 'PlanError';
		this.diagnostics = diagnostics;
	}
}

// --- Checksums and versions -----------------------------------------------------------

/** `sha256:<hex>` of the canonical JSON of `plan` without its `checksum` field. */
export const checksum = planChecksum;

function hashOf(value: Json): string {
	return `sha256:${toHex(sha256(utf8(canonicalJson(value))))}`;
}

/** The consent version (semantics.md §11): the checksum of the compiled consent texts. */
export function consentVersion(text: Json, agree: Json, decline: Json): string {
	return hashOf({ text, agree, decline });
}

/** The `surveyVersion` string fed to node_seed: the published version, or `"draft"`. */
export function seedVersion(survey: { version?: number | null }): string {
	const v = survey.version;
	return v === undefined || v === null ? 'draft' : String(v);
}

/** The `node_id` of one assigned variable's seeded draw: `<assign node>/<variable>`. */
export function seedNode(assignNodeId: string, variableId: string): string {
	return `${assignNodeId}/${variableId}`;
}

/** A copy of `plan` with `theme` at `plan.theme` and the checksum recomputed. */
export function embedTheme<P extends object>(plan: P, theme: Json): P & { theme: Json } {
	const out = { ...plan, theme } as P & { theme: Json; checksum?: string };
	out.checksum = checksum(out as Record<string, unknown>);
	return out;
}

// --- Text -----------------------------------------------------------------------------

const PIPE = /\$\{([^}]*)\}/g;
// Python's `$` also matches before one final newline; `(?:\n)?` keeps that.
const IDENT = /^[A-Za-z_][A-Za-z0-9_]*\n?$/;
const BUILTIN =
	/^\$(trial|position\.index|position\.of|pagesDone|language|device|response\.id|session\.id|outcome)\n?$/;

// `str.isspace()` code points (what Python's `str.strip()` removes).
const PY_SPACE = new Set([
	0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x1c, 0x1d, 0x1e, 0x1f, 0x20, 0x85, 0xa0, 0x1680, 0x2000, 0x2001,
	0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009, 0x200a, 0x2028, 0x2029, 0x202f,
	0x205f, 0x3000
]);

function pyStrSpaceStrip(s: string): string {
	let a = 0;
	let b = s.length;
	while (a < b && PY_SPACE.has(s.charCodeAt(a))) a++;
	while (b > a && PY_SPACE.has(s.charCodeAt(b - 1))) b--;
	return s.slice(a, b);
}

function pipeOk(inner: string): boolean {
	return IDENT.test(inner) || BUILTIN.test(inner);
}

/** Split one string at `${...}` pipes. Invalid pipes stay literal text. */
export function segments(text: string): CompiledSegment[] {
	const out: CompiledSegment[] = [];
	let pos = 0;
	for (const m of text.matchAll(PIPE)) {
		const inner = pyStrSpaceStrip(m[1]!);
		if (!pipeOk(inner)) continue;
		const start = m.index;
		if (start > pos) out.push(text.slice(pos, start));
		out.push({ pipe: inner });
		pos = start + m[0].length;
	}
	if (pos < text.length) out.push(text.slice(pos));
	return out;
}

function isObj(x: unknown): x is Obj {
	return typeof x === 'object' && x !== null && !Array.isArray(x);
}

/** A copy without `null`-valued keys (pydantic `exclude_none`), recursively. */
function dropNone(x: Json): Json {
	if (Array.isArray(x)) return x.map(dropNone);
	if (!isObj(x)) return x;
	const out: Obj = {};
	for (const [k, v] of Object.entries(x)) if (v !== null && v !== undefined) out[k] = dropNone(v);
	return out;
}

function runs(content: unknown): Json[] {
	return (content as Json[]).map((node) => {
		const pipe = isObj(node) ? node.pipe : undefined;
		if (typeof pipe === 'string' && !pipeOk(pipe)) return { text: '${' + pipe + '}' };
		return node;
	});
}

/** A rich tree as plan blocks (`osp_runtime.plan.blocks`): `null` fields dropped, an invalid
 * pipe node written back as literal `${…}` text. */
export function blocks(tree: Json): CompiledBlock[] {
	const data = dropNone(tree) as Obj;
	const out: CompiledBlock[] = [];
	for (const block of (data.blocks as Obj[] | undefined) ?? []) {
		if (block.type === 'ul' || block.type === 'ol') {
			out.push({ type: block.type, items: (block.items as unknown[]).map(runs) });
		} else {
			const copied: Obj = {};
			for (const [k, v] of Object.entries(block)) if (k !== 'content') copied[k] = v;
			copied.content = runs(block.content);
			out.push(copied);
		}
	}
	return out;
}

function isRich(x: unknown): boolean {
	return isObj(x) && x.type === 'rich';
}

// --- Expressions ----------------------------------------------------------------------

const MAX_SAFE_INT = 2n ** 53n - 1n;

/** Python's `str(Decimal(text))` for the decimal text forms `Decimal` accepts. */
export function pyDecimalText(value: string | number): string {
	let s: string;
	if (typeof value === 'number') {
		s = String(value);
	} else {
		s = pyStrSpaceStrip(value).replace(/(?<=\d)_(?=\d)/g, '');
	}
	const m = /^([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(s);
	if (!m || (m[2] === '' && (m[3] ?? '') === '')) throw new TypeError(`invalid decimal ${s}`);
	const sign = m[1] === '-' ? '-' : '';
	const frac = m[3] ?? '';
	let digits = (m[2]! + frac).replace(/^0+/, '') || '0';
	const exp = BigInt(m[4] ?? '0') - BigInt(frac.length);
	if (digits === '') digits = '0';
	const n = BigInt(digits.length);
	const adjusted = exp + n - 1n;
	if (exp <= 0n && adjusted >= -6n) {
		if (exp === 0n) return sign + digits;
		const point = Number(n + exp);
		if (point > 0) return `${sign}${digits.slice(0, point)}.${digits.slice(point)}`;
		return `${sign}0.${'0'.repeat(-point)}${digits}`;
	}
	const head = digits[0]! + (digits.length > 1 ? `.${digits.slice(1)}` : '');
	return `${sign}${head}E${adjusted >= 0n ? '+' : ''}${adjusted}`;
}

function intValue(v: unknown): Json {
	if (typeof v === 'bigint') return v > MAX_SAFE_INT || v < -MAX_SAFE_INT ? v.toString() : Number(v);
	if (typeof v === 'number' && Number.isInteger(v) && !Number.isSafeInteger(v)) {
		return BigInt(v).toString();
	}
	return v;
}

function ref(r: Json): Json {
	return { kind: 'ref', id: (r as Obj).id };
}

/** An `osp-expr` AST as plan JSON (`osp_runtime.plan.expr_json`): every field of the node,
 * a decimal literal's text as Python prints it, a big integer literal as decimal text. */
export function exprJson(e: Json): Json {
	const n = e as Obj;
	switch (n.kind) {
		case 'int':
			return { kind: 'int', value: intValue(n.value) };
		case 'decimal':
			return { kind: 'decimal', value: pyDecimalText(n.value as string | number) };
		case 'text':
		case 'bool':
			return { kind: n.kind, value: n.value };
		case 'null':
			return { kind: 'null' };
		case 'ref':
			return ref(n);
		case 'compare':
		case 'arith':
			return { kind: n.kind, op: n.op, left: exprJson(n.left), right: exprJson(n.right) };
		case 'and':
		case 'or':
			return { kind: n.kind, args: (n.args as Json[]).map(exprJson) };
		case 'not':
			return { kind: 'not', arg: exprJson(n.arg) };
		case 'answered':
			return { kind: 'answered', ref: ref(n.ref) };
		case 'contains':
			return { kind: 'contains', ref: ref(n.ref), value: exprJson(n.value) };
		case 'if':
			return { kind: 'if', cond: exprJson(n.cond), then: exprJson(n.then), else: exprJson(n.else) };
	}
	throw new TypeError(`unknown expression kind ${String(n.kind)}`);
}

// --- Runtime config -------------------------------------------------------------------

export interface RuntimeConfigJson {
	surveyVersion: string;
	saveMode: string;
	resumeExpiryDays: number;
	assignments: Array<{ variable: string; levels: unknown[]; method: 'simple'; seedNode: string }>;
	quotas: Array<{ node: string; quota: string; limit: number }>;
	external?: string[];
	consent?: { version: string; countDeclines: boolean };
}

/** The `RuntimeConfig` JSON the session service needs beside the plan
 * (`osp_runtime.plan.runtime_config`). `saveMode` overrides the survey's save mode. */
export function runtimeConfig(plan: Plan | Obj, options: { saveMode?: string | null } = {}): RuntimeConfigJson {
	const p = plan as Obj;
	const quotaMap = p.quotas as Record<string, Obj>;
	const quotas: RuntimeConfigJson['quotas'] = [];
	const external: string[] = [];
	const walk = (nodes: Obj[]): void => {
		for (const n of nodes) {
			if (n.type === 'quotaCheck') {
				const q = quotaMap[n.quota as string] ?? {};
				quotas.push({ node: n.id as string, quota: n.quota as string, limit: (q.limit as number) ?? 0 });
			} else if (n.type === 'externalTask') {
				external.push(n.id as string);
			} else if (n.type === 'branch') {
				walk(n.then as Obj[]);
				walk(n.else as Obj[]);
			} else if (n.type === 'randomiser') {
				walk(n.children as Obj[]);
			}
		}
	};
	walk(p.flow as Obj[]);
	const assignments = Object.values(p.variables as Record<string, Obj>)
		.filter((v) => v.kind === 'assigned')
		.map((v) => ({
			variable: v.id as string,
			levels: [...(v.levels as unknown[])],
			method: 'simple' as const,
			seedNode: v.seedNode as string
		}));
	const settings = (p.settings as Obj | undefined) ?? {};
	const out: RuntimeConfigJson = {
		surveyVersion: (p.survey as Obj).seedVersion as string,
		saveMode: options.saveMode || ((settings.saveMode as string | undefined) ?? 'every-page'),
		resumeExpiryDays: (settings.resumeExpiryDays as number | undefined) ?? 30,
		assignments,
		quotas
	};
	if (external.length) out.external = external;
	const consent = p.consent as Obj | undefined;
	if (consent && Object.keys(consent).length) {
		out.consent = { version: consent.version as string, countDeclines: Boolean(consent.countDeclines) };
	}
	return out;
}

// --- The compiler ---------------------------------------------------------------------

function byKey<T>(o: Record<string, T>): Array<[string, T]> {
	// Python `sorted(dict.items())`; the order never reaches the canonical JSON, but keeps the
	// object's insertion order the same as Python's.
	return Object.entries(o).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
}

const QUESTION_TYPES_WITH_BOUNDS = new Set(['integer', 'decimal']);

class Compiler {
	private readonly s: Obj;
	private readonly languages: string[];
	private readonly defaultLanguage: string;
	private readonly lists = new Map<string, Json[]>();
	private readonly items: Obj = {};
	private readonly pages: Obj = {};
	private readonly blocks: Record<string, { id: string; pages: string[] }> = {};
	private readonly questions: string[] = [];
	private readonly seedNodes = new Map<string, string>();

	constructor(survey: Obj) {
		this.s = survey;
		const md = survey.metadata as Obj;
		this.languages = [...(md.languages as string[])];
		this.defaultLanguage = (md.defaultLanguage as string | null | undefined) || this.languages[0]!;
		for (const cl of (survey.choiceLists as Obj[] | undefined) ?? []) {
			this.lists.set(cl.id as string, cl.choices as Json[]);
		}
	}

	private value(text: Json): Json {
		return typeof text === 'string' ? segments(text) : blocks(text);
	}

	text(text: Json): Json {
		if (text === null || text === undefined) return null;
		const out: Obj = {};
		if (typeof text === 'string' || isRich(text)) {
			for (const lang of this.languages) out[lang] = this.value(text);
			return out;
		}
		const map = text as Obj;
		let fallback = Object.hasOwn(map, this.defaultLanguage) ? map[this.defaultLanguage] : undefined;
		if (fallback === undefined || fallback === null) {
			const values = Object.values(map);
			fallback = values.length ? values[0] : '';
		}
		for (const lang of this.languages) out[lang] = this.value(Object.hasOwn(map, lang) ? map[lang] : fallback);
		return out;
	}

	private expr(e: Json): Json {
		return e === null || e === undefined ? null : exprJson(e);
	}

	private choices(choices: Json[]): Json[] {
		return choices.map((c) => ({ value: (c as Obj).value, label: this.text((c as Obj).label) }));
	}

	private columns(q: Obj): Json[] {
		const source = q.choices != null ? (q.choices as Json[]) : this.lists.get((q.choiceList as string) || '');
		return source ?? [];
	}

	private item(q: Obj, pageId: string): Obj {
		const out: Obj = { id: q.id, type: q.type, page: pageId };
		out.label = this.text(q.label);
		if (q.help != null) out.help = this.text(q.help);
		if (q.showIf != null) out.showIf = this.expr(q.showIf);
		if (q.type === 'note') return out;
		out.name = q.name || q.id;
		out.required = (q.required as boolean | null | undefined) ?? false;
		if (q.type === 'text' && q.multiline === true) out.multiline = true;
		if (q.type === 'matrix') {
			out.rows = (q.rows as Obj[]).map((r) => `${q.id as string}_${r.id as string}`);
			out.choices = this.choices(this.columns(q));
			return out;
		}
		if (q.constraint != null) out.constraint = this.expr(q.constraint);
		if (q.constraintMessage != null) out.constraintMessage = this.text(q.constraintMessage);
		if (q.type === 'slider') {
			out.valueType = q.valueType ?? 'integer';
			out.step = q.step ?? 1;
			for (const key of ['minLabel', 'maxLabel']) if (q[key] != null) out[key] = this.text(q[key]);
			out.min = q.min ?? 0;
			out.max = q.max ?? 100;
		} else if (QUESTION_TYPES_WITH_BOUNDS.has(q.type as string)) {
			for (const key of ['min', 'max']) if (q[key] != null) out[key] = q[key];
		}
		if (q.type === 'single' || q.type === 'multi') {
			out.choices = this.choices(this.columns(q));
			out.choiceOrder = q.choiceOrder ?? 'fixed';
		}
		return out;
	}

	private rows(q: Obj, pageId: string): Obj[] {
		const choices = this.choices(this.columns(q));
		const name = (q.name as string | null | undefined) || (q.id as string);
		return (q.rows as Obj[]).map((r) => ({
			id: `${q.id as string}_${r.id as string}`,
			type: 'single',
			page: pageId,
			label: this.text(r.label),
			name: `${name}_${r.id as string}`,
			required: r.required == null ? ((q.required as boolean | null | undefined) ?? false) : r.required,
			choices,
			choiceOrder: 'fixed',
			matrix: q.id
		}));
	}

	block(blockId: string): string[] {
		const known = this.blocks[blockId];
		if (known) return known.pages;
		const block = ((this.s.blocks as Obj[] | undefined) ?? []).find((b) => b.id === blockId);
		const pageIds: string[] = [];
		if (block) {
			for (const page of block.pages as Obj[]) {
				const pid = page.id as string;
				pageIds.push(pid);
				const items = page.items as Obj[];
				for (const q of items) {
					this.items[q.id as string] = this.item(q, pid);
					if (q.type === 'matrix') {
						for (const row of this.rows(q, pid)) {
							this.items[row.id as string] = row;
							this.questions.push(row.id as string);
						}
					} else if (q.type !== 'note') {
						this.questions.push(q.id as string);
					}
				}
				const compiled: Obj = {
					id: pid,
					block: blockId,
					items: items.map((q) => q.id),
					itemOrder: page.itemOrder ?? 'fixed'
				};
				if (page.showIf != null) compiled.showIf = this.expr(page.showIf);
				this.pages[pid] = compiled;
			}
		}
		this.blocks[blockId] = { id: blockId, pages: pageIds };
		return pageIds;
	}

	private node(n: Obj): Obj {
		switch (n.type) {
			case 'block':
				return { type: 'block', id: n.id, block: n.block, pages: this.block(n.block as string) };
			case 'branch':
				return {
					type: 'branch',
					id: n.id,
					if: this.expr(n.if),
					then: (n.then as Obj[]).map((c) => this.node(c)),
					else: ((n.else as Obj[] | undefined) ?? []).map((c) => this.node(c))
				};
			case 'randomiser':
				return {
					type: 'randomiser',
					id: n.id,
					children: (n.children as Obj[]).map((c) => this.node(c)),
					pick: n.pick ?? null
				};
			case 'assign':
				for (const v of n.variables as string[]) {
					if (!this.seedNodes.has(v)) this.seedNodes.set(v, seedNode(n.id as string, v));
				}
				return { type: 'assign', id: n.id, variables: [...(n.variables as string[])] };
			case 'quotaCheck':
				return { type: 'quotaCheck', id: n.id, quota: n.quota };
			case 'externalTask': {
				const returns: Obj[] = [];
				const variables = (this.s.variables as Obj[] | undefined) ?? [];
				for (const vid of (n.returns as string[] | undefined) ?? []) {
					const v = variables.find((x) => x.id === vid);
					if (v && v.kind === 'embedded') returns.push({ variable: vid, param: v.param });
				}
				return {
					type: 'externalTask',
					id: n.id,
					template: n.template,
					params: this.params(n.params),
					returns
				};
			}
			case 'end': {
				const out: Obj = { type: 'end', id: n.id, outcome: n.outcome ?? 'complete' };
				if (n.message != null) out.message = this.text(n.message);
				return out;
			}
		}
		throw new TypeError(`unknown flow node ${String(n.type)}`);
	}

	private params(params: unknown): Obj {
		const out: Obj = {};
		for (const [k, v] of byKey((params as Record<string, string> | null | undefined) ?? {})) {
			out[k] = segments(v);
		}
		return out;
	}

	private variable(v: Obj): Obj {
		const out: Obj = { id: v.id, kind: v.kind, name: v.name || v.id };
		if (v.kind === 'embedded') {
			out.valueType = v.valueType ?? 'text';
			out.source = v.source ?? 'url';
			out.param = v.param;
			out.default = v.default ?? null;
		} else if (v.kind === 'assigned') {
			out.levels = [...(v.levels as unknown[])];
			out.seedNode = this.seedNodes.get(v.id as string) ?? v.id;
		} else if (v.kind === 'computed') {
			out.expr = this.expr(v.expr);
		}
		return out;
	}

	run(hooksOption: Json): Obj {
		const s = this.s;
		const flow = ((s.flow as Obj[] | undefined) ?? []).map((n) => this.node(n));
		const quotas: Obj = {};
		for (const q of (s.quotas as Obj[] | undefined) ?? []) {
			const onFull = q.onFull as Obj;
			const block = (onFull.block as string | null | undefined) ?? null;
			quotas[q.id as string] = {
				id: q.id,
				when: this.expr(q.when),
				limit: q.limit,
				countOn: q.countOn ?? 'complete',
				onFull: { outcome: onFull.outcome, block, pages: block ? this.block(block) : [] }
			};
		}
		const settings = (s.settings as Obj | null | undefined) ?? {};
		const variables: Obj = {};
		for (const v of (s.variables as Obj[] | undefined) ?? []) variables[v.id as string] = this.variable(v);
		const plan: Obj = {
			planVersion: PLAN_VERSION,
			engineVersion: ENGINE_VERSION,
			checksum: '',
			survey: {
				id: s.id,
				version: s.version ?? null,
				specVersion: s.specVersion,
				seedVersion: seedVersion(s as { version?: number | null })
			},
			languages: this.languages,
			defaultLanguage: this.defaultLanguage,
			title: this.text((s.metadata as Obj).title),
			settings: {
				backNavigation: settings.backNavigation ?? true,
				saveMode: settings.saveMode ?? 'every-page',
				localCopy: settings.localCopy ?? 'browser',
				resumeExpiryDays: settings.resumeExpiryDays ?? 30
			},
			items: this.items,
			questions: this.questions,
			pages: this.pages,
			blocks: this.blocks,
			variables,
			quotas,
			flow
		};
		const c = s.consent as Obj | null | undefined;
		if (c != null) {
			const text = this.text(c.text);
			const agree = this.text(c.agreeLabel ?? 'I agree');
			const decline = this.text(c.declineLabel ?? 'I do not agree');
			plan.consent = {
				version: consentVersion(text, agree, decline),
				text,
				agree,
				decline,
				declineOutcome: c.declineOutcome ?? 'declined',
				countDeclines: c.countDeclines ?? false
			};
		}
		const endingsIn = (settings.endings as Record<string, Obj> | null | undefined) ?? {};
		if (Object.keys(endingsIn).length) {
			const endings: Obj = {};
			for (const [outcome, e] of byKey(endingsIn)) {
				const ending: Obj = { status: e.status ?? 'auto', summary: e.summary ?? 'none' };
				if (e.title != null) ending.title = this.text(e.title);
				if (e.body != null) ending.body = this.text(e.body);
				const r = e.redirect as Obj | null | undefined;
				if (r != null) {
					const redirect: Obj = {
						template: r.template,
						params: this.params(r.params),
						delay: r.delay ?? 5,
						mode: r.mode ?? 'auto'
					};
					if (r.label != null) redirect.label = this.text(r.label);
					ending.redirect = redirect;
				}
				endings[outcome] = ending;
			}
			plan.endings = endings;
		}
		let hooks: Json = hooksOption;
		if ((hooks === null || hooks === undefined) && s.hooks != null) hooks = dropNone(s.hooks);
		const settingsTemplates: Obj = {};
		for (const [name, t] of byKey((settings.redirectTemplates as Record<string, Obj> | null | undefined) ?? {})) {
			settingsTemplates[name] = dropNone(t);
		}
		const hasSettingsTemplates = Object.keys(settingsTemplates).length > 0;
		if (hooks !== null && hooks !== undefined) {
			if (hasSettingsTemplates) {
				const h = hooks as Obj;
				hooks = { ...h, redirects: { ...settingsTemplates, ...((h.redirects as Obj | null) || {}) } };
			}
			plan.hooks = hooks;
		}
		const hookRedirects = isObj(hooks) ? ((hooks.redirects as Obj | null) || {}) : {};
		const templates: Obj = { ...hookRedirects, ...settingsTemplates };
		if (Object.keys(templates).length) {
			const sorted: Obj = {};
			for (const [k, v] of byKey(templates)) sorted[k] = v;
			plan.redirectTemplates = sorted;
		}
		plan.checksum = checksum(plan);
		return plan;
	}
}

function deepCopy(x: Json): Json {
	return x === undefined ? undefined : (JSON.parse(JSON.stringify(x)) as Json);
}

function internalError(e: unknown): PlanDiagnostic {
	const name = e instanceof Error ? e.name : typeof e;
	return { severity: 'error', code: 'internal.error', pointer: '', message: `plan: ${name}` };
}

/**
 * Compile a survey document (raw `osp-survey` JSON) into a runtime plan, as
 * `osp_runtime.plan.compile_plan` does. Throws `PlanError` when `validate` reports errors
 * or when the document cannot be compiled.
 */
export function compilePlan(survey: unknown, options: CompileOptions = {}): Plan {
	const { plan, diagnostics } = compileSurvey(survey, options);
	if (plan === null) throw new PlanError(diagnostics.filter((d) => d.severity === 'error'));
	return plan;
}

/**
 * Validate (with `options.validate`, if given) and compile raw survey JSON, as
 * `osp_runtime.plan.compile_survey` does. Never throws: `{plan: null, diagnostics}` when the
 * survey is refused.
 */
export function compileSurvey(
	data: unknown,
	options: CompileOptions = {}
): { plan: Plan | null; diagnostics: PlanDiagnostic[] } {
	const hooks = options.hooks;
	let input = data;
	if (hooks !== undefined && hooks !== null && isObj(data)) input = { ...data, hooks };
	let diagnostics: PlanDiagnostic[] = [];
	try {
		if (options.validate) diagnostics = options.validate(input);
	} catch (e) {
		return { plan: null, diagnostics: [internalError(e)] };
	}
	if (diagnostics.some((d) => d.severity === 'error')) return { plan: null, diagnostics };
	if (!isObj(input)) return { plan: null, diagnostics: [...diagnostics, internalError(new TypeError())] };
	try {
		const plan = new Compiler(input).run(deepCopy(hooks ?? null));
		return { plan: plan as unknown as Plan, diagnostics };
	} catch (e) {
		return { plan: null, diagnostics: [...diagnostics, internalError(e)] };
	}
}
