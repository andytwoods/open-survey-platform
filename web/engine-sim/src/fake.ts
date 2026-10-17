/**
 * Fake participants for local dev (task DS1, `osp-cli fake-responses`): one invented but
 * realistic participant at a time, driven through the real participant engine exactly as
 * the participant app drives it. The engine decides everything (page order, relevance,
 * validation, randomiser orders, ends); this module only plays the participant: it picks
 * answers, spends time on each page, and talks to the server through `ask` (consent,
 * snapshot saves, quota checks, submit), the same calls the runtime's session makes.
 *
 * Answers follow plausible shapes rather than uniform noise:
 * - each participant has a latent attitude (`z`, shifted a little by their assigned
 *   conditions), an engagement level (optional questions and free text get skipped more by
 *   the less engaged) and a speed;
 * - single choice: skewed, Zipf-like popularity per question; ordered scales (numeric
 *   codes in ascending order, at least 4) and matrix rows: an ordinal draw with a lean per
 *   question, driven by `z` (rows of one matrix share a factor, so they correlate);
 * - multiple choice: 1–3 picks weighted by per-option popularity;
 * - numbers: within min/max a clipped normal (rounded, on the slider step grid); without
 *   bounds a skewed count, or by label words an age, hours or a price;
 * - dates: within a year the label names, else in the months before the session;
 * - free text: short invented phrases (no real personal data), by topic and language.
 *
 * Pure apart from `ask`: no clock, no Math.random. Same plan, seed and spec ⇒ same answers.
 */

import {
	agree,
	answer,
	awaitingConsent,
	context,
	next,
	resolve,
	result,
	snapshot,
	start,
	view,
	type ChoiceValue,
	type Device,
	type Id,
	type Plan,
	type QuestionItem,
	type ResponseRecord,
	type Snapshot,
	type State,
	type Text
} from '@osp/engine';
import { rng as makeRng, type Rng } from './prng.ts';
import { representative, sliderCount, sliderPoint } from './structure.ts';

export const FAKE_FORMAT = 'osp-fake/1';

/** One participant, as the server started them. */
export interface ParticipantSpec {
	/** Position in the run (with the run's seed, it seeds this participant's choices). */
	index: number;
	sessionSeed: number;
	assigned: Record<Id, ChoiceValue>;
	sessionId: string;
	/** Epoch ms the session starts; the engine's clock runs from here. */
	startMs: number;
	/** Drop out part-way: the fraction (0 … 1) of the expected pages done first; null: finish. */
	dropAt: number | null;
	saveMode: 'every-page' | 'end-only';
}

/** What the participant asks the server to do (the runtime's API calls), at engine time `at`. */
export type Ask =
	| { do: 'consent'; at: number; version: string }
	| { do: 'save'; at: number; snapshot: Snapshot }
	| { do: 'quota'; at: number; node: Id }
	| { do: 'submit'; at: number; record: ResponseRecord };

export interface AskReply {
	/** For `quota`: the server's answer. */
	result?: 'open' | 'full';
}

export interface ParticipantOutcome {
	submitted: boolean;
	/** The end outcome when submitted (e.g. `complete`, `quota_full`). */
	end: string | null;
	/** Dropped out (not submitted) on this page; `stuck`: no valid answer could be found. */
	droppedOn: Id | null;
	stuck: boolean;
	pages: number;
	language: string;
	device: Device;
	/** The engine's record at the end (also for a drop-out: what the server's copy holds). */
	record: ResponseRecord;
}

// --- Small maths ------------------------------------------------------------------------------

function strHash(s: string): number {
	let h = 0x811c9dc5;
	for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 0x01000193) >>> 0;
	return h;
}

function mix(a: number, b: number): number {
	let h = (Math.imul((a >>> 0) ^ 0x9e3779b9, 0x85ebca6b) ^ Math.imul(b >>> 0, 0xc2b2ae35)) >>> 0;
	h = Math.imul(h ^ (h >>> 16), 0x7feb352d) >>> 0;
	return (h ^ (h >>> 15)) >>> 0;
}

function normal(r: Rng): number {
	const u = Math.max(r(), 1e-12);
	return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * r());
}

function clamp(x: number, lo: number, hi: number): number {
	return Math.min(hi, Math.max(lo, x));
}

/** Standard normal CDF (Abramowitz–Stegun 7.1.26, error < 1.5e-7). */
function phi(x: number): number {
	const t = 1 / (1 + (0.3275911 * Math.abs(x)) / Math.SQRT2);
	const y = 1 - ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp((-x * x) / 2);
	return x >= 0 ? (1 + y) / 2 : (1 - y) / 2;
}

function poisson(r: Rng, lambda: number): number {
	const l = Math.exp(-Math.min(lambda, 60));
	let k = 0;
	for (let p = r(); p > l && k < 500; p *= r()) k++;
	return k;
}

function weighted<T>(r: Rng, xs: readonly T[], w: readonly number[]): number {
	const total = w.reduce((a, b) => a + b, 0);
	let roll = r() * total;
	for (let i = 0; i < xs.length; i++) {
		roll -= w[i]!;
		if (roll < 0) return i;
	}
	return xs.length - 1;
}

function num(v: number | string | undefined): number | null {
	if (v === undefined) return null;
	const n = Number(v);
	return Number.isFinite(n) ? n : null;
}

function decimalText(x: number): string {
	const s = String(Number(x.toFixed(2)));
	return s.includes('e') ? x.toFixed(2) : s;
}

function plain(text: Text | undefined, lang: string, fallback: string): string {
	const segs = text?.[lang] ?? text?.[fallback] ?? [];
	return segs.map((s) => (typeof s === 'string' ? s : ' ')).join('');
}

// --- Free text --------------------------------------------------------------------------------

type Topic = 'weather' | 'reason' | 'describe' | 'comment';

const PHRASES: Record<string, Record<Topic, string[]>> = {
	en: {
		weather: [
			'Sunny but cold.',
			'Grey and drizzly all morning.',
			'Windy, with a few showers.',
			'Warm and bright.',
			'Overcast, it might rain later.',
			'Clear skies, quite chilly.',
			'Heavy rain on the way in.',
			'Mild and cloudy.',
			'Foggy first thing, then sunny.',
			'Hot and a bit humid.',
			'Frost on the car this morning.',
			'Nice enough, some cloud.'
		],
		reason: [
			'I like the taste.',
			'It wakes me up.',
			'Habit, mostly.',
			'It is what we have at work.',
			'It is cheaper.',
			'Better for me than the alternatives.',
			'It reminds me of home.',
			'A friend got me into it.',
			'I just enjoy it.',
			'It goes well with breakfast.',
			'Less sugar than the others.',
			'No real reason.'
		],
		describe: [
			'Plain wooden one with four legs.',
			'Something comfortable to read in.',
			'Simple, nothing special.',
			'Soft, with a high back.',
			'Light and easy to move around.',
			'Quite ordinary really.',
			'Bright colours and rounded edges.',
			'Sturdy and practical.'
		],
		comment: [
			'No comments.',
			'All fine, thanks.',
			'Quick and easy to fill in.',
			'Some questions were a bit vague.',
			'Nothing to add.',
			'Interesting topic.',
			'It took longer than I expected.',
			'I was not sure about one answer.',
			'Thanks!',
			'Clear questions.',
			'Happy to help.',
			'Fine.',
			'Would be good to see the results.',
			'One of the questions was hard to answer on my phone.'
		]
	},
	de: {
		weather: ['Sonnig, aber kalt.', 'Bewölkt und windig.', 'Regnerisch.', 'Warm und freundlich.', 'Nebelig am Morgen.'],
		reason: ['Es schmeckt mir.', 'Aus Gewohnheit.', 'Es macht wach.', 'Es ist günstiger.', 'Ich mag es einfach.', 'Gibt es bei der Arbeit.'],
		describe: ['Ein einfacher Holzstuhl.', 'Bequem und weich.', 'Nichts Besonderes.', 'Leicht und stabil.'],
		comment: ['Keine Anmerkungen.', 'Alles gut.', 'Danke!', 'Nichts hinzuzufügen.', 'Interessante Fragen.', 'Etwas lang.']
	}
};

function topicOf(label: string): Topic {
	if (/weather|wetter|rain|sunny/i.test(label)) return 'weather';
	if (/\bwhy\b|warum|reason|because|what helps|grund/i.test(label)) return 'reason';
	if (/describe|beschreib|design/i.test(label)) return 'describe';
	return 'comment';
}

// --- Per-question shapes ----------------------------------------------------------------------

type Shape =
	| { kind: 'nominal'; weights: number[] }
	| { kind: 'ordinal'; lean: number; loading: number }
	| { kind: 'multi'; popularity: number[] }
	| { kind: 'normal'; centre: number; sd: number; lo: number | null; hi: number | null }
	| { kind: 'count'; mean: number; lo: number | null; hi: number | null }
	| { kind: 'lognormal'; median: number; sigma: number; lo: number | null; hi: number | null }
	| { kind: 'slider'; centre: number; sd: number }
	| { kind: 'date'; year: number | null; centreDay: number }
	| { kind: 'text'; topic: Topic };

function ordered(codes: readonly ChoiceValue[]): boolean {
	if (codes.length < 4) return false;
	const ns = codes.map((c) => Number(c));
	return ns.every((n) => Number.isFinite(n)) && ns.every((n, i) => i === 0 || n > ns[i - 1]!);
}

function numberShape(q: QuestionItem, label: string, r: Rng): Shape {
	const lo = num(q.min);
	const hi = num(q.max);
	if (lo !== null && hi !== null && hi > lo) {
		const range = hi - lo;
		return { kind: 'normal', centre: lo + (0.3 + 0.4 * r()) * range, sd: range * (0.12 + 0.1 * r()), lo, hi };
	}
	const l = label.toLowerCase();
	if (/\bage\b|how old|\balter\b|wie alt/.test(l)) return { kind: 'normal', centre: 36 + 6 * r(), sd: 12, lo: lo ?? 18, hi: hi ?? 85 };
	if (/hours?|stunden/.test(l)) return { kind: 'normal', centre: 6.6 + 0.8 * r(), sd: 1.2, lo: lo ?? 0, hi: hi ?? 16 };
	if (/cost|price|pay|spend|pounds|euro|dollar|£|€|\$|kost|preis/.test(l)) {
		return { kind: 'lognormal', median: 2.6 + r(), sigma: 0.25 + 0.1 * r(), lo: lo ?? 0, hi };
	}
	if (q.type === 'decimal') return { kind: 'lognormal', median: 2 + 8 * r(), sigma: 0.5, lo: lo ?? 0, hi };
	return { kind: 'count', mean: 1.5 + 2.5 * r(), lo: lo ?? 0, hi };
}

class Shapes {
	private readonly cache = new Map<Id, Shape>();
	constructor(
		private readonly plan: Plan,
		private readonly seed: number
	) {}

	label(q: QuestionItem): string {
		const parent = q.matrix ? this.plan.items[q.matrix] : undefined;
		const p = this.plan;
		const lang = p.languages.includes('en') ? 'en' : p.defaultLanguage;
		return `${plain(parent?.label, lang, p.defaultLanguage)} ${plain(q.label, lang, p.defaultLanguage)}`.trim();
	}

	get(q: QuestionItem): Shape {
		const hit = this.cache.get(q.id);
		if (hit) return hit;
		const r = makeRng(mix(this.seed, strHash(q.id)));
		const label = this.label(q);
		const choices = q.choices ?? [];
		let s: Shape;
		switch (q.type) {
			case 'single':
				if (q.matrix || ordered(choices.map((c) => c.value))) {
					s = { kind: 'ordinal', lean: 0.25 + 0.55 * normal(r), loading: 0.6 + 0.4 * r() };
				} else {
					const rank = choices.map((_, i) => i);
					for (let i = rank.length - 1; i > 0; i--) {
						const j = Math.floor(r() * (i + 1));
						[rank[i], rank[j]] = [rank[j]!, rank[i]!];
					}
					// A yes/no question: most people say yes.
					const p = this.plan;
					const yes = choices.findIndex((c) => /^(yes|ja|oui|s[ií])\b/i.test(plain(c.label, 'en', p.defaultLanguage).trim()));
					if (yes >= 0 && choices.length <= 3) {
						const top = rank.indexOf(0);
						[rank[top], rank[yes]] = [rank[yes]!, 0];
					}
					s = { kind: 'nominal', weights: choices.map((_, i) => (0.5 + r()) / (rank[i]! + 1) ** 1.1) };
				}
				break;
			case 'multi':
				s = { kind: 'multi', popularity: choices.map(() => 0.15 + 0.7 * r() ** 1.5) };
				break;
			case 'integer':
			case 'decimal':
				s = numberShape(q, label, r);
				break;
			case 'slider':
				s = { kind: 'slider', centre: 0.3 + 0.4 * r(), sd: 0.14 + 0.08 * r() };
				break;
			case 'date': {
				const m = /\b(19\d{2}|20\d{2})\b/.exec(label);
				s = { kind: 'date', year: m ? Number(m[1]) : null, centreDay: 30 + Math.floor(300 * r()) };
				break;
			}
			case 'text':
				s = { kind: 'text', topic: topicOf(label) };
				break;
		}
		this.cache.set(q.id, s);
		return s;
	}
}

// --- The participant --------------------------------------------------------------------------

interface Persona {
	z: number;
	engagement: number;
	speed: number;
	language: string;
	device: Device;
	/** Per matrix: the factor its rows share. */
	matrix: Map<Id, number>;
}

function persona(plan: Plan, spec: ParticipantSpec, r: Rng): Persona {
	// Conditions nudge the attitude, so splits by condition show a (small) difference.
	let shift = 0;
	for (const [id, level] of Object.entries(spec.assigned)) {
		const v = plan.variables[id];
		if (v?.kind !== 'assigned' || v.levels.length < 2) continue;
		const i = v.levels.findIndex((l) => String(l) === String(level));
		shift += 0.35 * (i / (v.levels.length - 1) - 0.5);
	}
	const langs = plan.languages;
	const others = langs.filter((l) => l !== plan.defaultLanguage);
	const language = others.length && r() < 0.3 ? others[Math.floor(r() * others.length)]! : plan.defaultLanguage;
	const d = r();
	return {
		z: normal(r) + shift,
		engagement: clamp(0.68 + 0.2 * normal(r), 0.1, 1),
		speed: Math.exp(0.35 * normal(r)),
		language,
		device: d < 0.55 ? 'phone' : d < 0.93 ? 'desktop' : 'tablet',
		matrix: new Map()
	};
}

const BLANK = null;
type Value = ChoiceValue | ChoiceValue[] | null;

function skipProbability(q: QuestionItem, p: Persona): number {
	if (q.required) return 0;
	if (q.type === 'text') return clamp(0.18 + 0.45 * (1 - p.engagement), 0, 0.9);
	if (q.type === 'slider') return 0.06 + 0.15 * (1 - p.engagement);
	return 0.02 + 0.08 * (1 - p.engagement);
}

function pad(n: number): string {
	return String(n).padStart(2, '0');
}

function isoDay(ms: number): string {
	const d = new Date(ms);
	return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
}

function draw(q: QuestionItem, shape: Shape, p: Persona, r: Rng, nowMs: number): Value {
	if (r() < skipProbability(q, p)) return BLANK;
	const choices = q.choices ?? [];
	switch (shape.kind) {
		case 'nominal':
			return choices.length ? choices[weighted(r, choices, shape.weights)]!.value : BLANK;
		case 'ordinal': {
			if (!choices.length) return BLANK;
			let factor = p.z;
			if (q.matrix) {
				if (!p.matrix.has(q.matrix)) p.matrix.set(q.matrix, 0.75 * p.z + 0.66 * normal(r));
				factor = p.matrix.get(q.matrix)!;
			}
			const latent = shape.lean + shape.loading * factor + 0.7 * normal(r);
			const k = clamp(Math.floor(phi(latent / 1.25) * choices.length), 0, choices.length - 1);
			return choices[k]!.value;
		}
		case 'multi': {
			if (!choices.length) return BLANK;
			const roll = r();
			const want = Math.min(choices.length, roll < 0.45 ? 1 : roll < 0.8 ? 2 : 3);
			const left = choices.map((_, i) => i);
			const w = [...shape.popularity];
			const picked: number[] = [];
			while (picked.length < want && left.length) {
				const j = weighted(r, left, left.map((i) => w[i]!));
				picked.push(left[j]!);
				left.splice(j, 1);
			}
			// Keep the options' declared order, as a checkbox list sends them.
			return picked.sort((a, b) => a - b).map((i) => choices[i]!.value);
		}
		case 'normal':
		case 'count':
		case 'lognormal': {
			let x: number;
			if (shape.kind === 'normal') x = shape.centre + shape.sd * (0.35 * p.z + 0.94 * normal(r));
			else if (shape.kind === 'count') x = poisson(r, shape.mean * Math.exp(0.6 * normal(r) - 0.18));
			else x = shape.median * Math.exp(shape.sigma * normal(r));
			if (shape.lo !== null) x = Math.max(shape.lo, x);
			if (shape.hi !== null) x = Math.min(shape.hi, x);
			if (q.type === 'integer') {
				const lo = shape.lo === null ? -Infinity : Math.ceil(shape.lo);
				const hi = shape.hi === null ? Infinity : Math.floor(shape.hi);
				return clamp(Math.round(x), lo, hi);
			}
			return decimalText(x);
		}
		case 'slider': {
			const n = sliderCount(q);
			const f = clamp(shape.centre + shape.sd * (0.4 * p.z + 0.9 * normal(r)), 0, 1);
			return sliderPoint(q, Math.round(f * (n - 1))) as ChoiceValue;
		}
		case 'date': {
			if (shape.year !== null) {
				const day = clamp(Math.round(shape.centreDay + 70 * normal(r)), 0, 364);
				return isoDay(Date.UTC(shape.year, 0, 1) + day * 86_400_000);
			}
			const back = Math.min(3650, Math.floor(-Math.log(Math.max(r(), 1e-9)) * 120));
			return isoDay(nowMs - back * 86_400_000);
		}
		case 'text': {
			const bank = PHRASES[p.language] ?? PHRASES['en']!;
			const pool = bank[shape.topic];
			const first = pool[Math.floor(r() * pool.length)]!;
			if (p.engagement > 0.75 && r() < 0.3) {
				const extra = pool[Math.floor(r() * pool.length)]!;
				if (extra !== first) return `${first} ${extra}`;
			}
			return first;
		}
	}
}

/** Seconds a participant spends on one answer (before their speed). */
const THINK: Record<string, number> = { single: 4, multi: 7, integer: 6, decimal: 7, slider: 5, date: 8, text: 22 };

const MAX_RETRIES = 20;

/**
 * The questions on the current page the participant can answer, in display order (matrix
 * rows in their row order), live show-if included.
 */
function visibleQuestions(state: State): Id[] {
	const out: Id[] = [];
	for (const it of view(state).items) {
		if (it.rows) for (const row of it.rows) out.push(row.id);
		else if (it.state !== null) out.push(it.id);
	}
	return out;
}

export class FakeParticipants {
	private readonly shapes: Shapes;

	constructor(
		readonly plan: Plan,
		readonly seed: number
	) {
		start(plan, { sessionSeed: 1, clock: () => 0 }); // validates the plan (checksum, versions)
		this.shapes = new Shapes(plan, seed);
	}

	/** Play one participant from start to submit (or drop-out), asking the server as it goes. */
	async run(spec: ParticipantSpec, ask: (a: Ask) => Promise<AskReply>): Promise<ParticipantOutcome> {
		const plan = this.plan;
		const r = makeRng(mix(mix(this.seed, 0x51ed), spec.index));
		const p = persona(plan, spec, r);
		let t = spec.startMs;
		const clock = () => t;
		const wait = (seconds: number) => {
			t += Math.max(200, Math.round(seconds * 1000 * p.speed * Math.exp(0.35 * normal(r))));
		};
		const everyPage = spec.saveMode === 'every-page';
		let state = start(plan, {
			sessionSeed: spec.sessionSeed,
			assigned: spec.assigned,
			clock,
			language: p.language,
			device: p.device,
			urlParams: {},
			sessionId: spec.sessionId
		});
		const save = async () => {
			if (everyPage && !awaitingConsent(state)) await ask({ do: 'save', at: t, snapshot: snapshot(state) });
		};
		if (plan.consent && awaitingConsent(state)) {
			wait(10);
			await ask({ do: 'consent', at: t, version: plan.consent.version });
			state = agree(state);
		}
		await save();

		let pages = 0;
		let dropPage: number | null = null;
		const outcome = (o: Partial<ParticipantOutcome>): ParticipantOutcome => ({
			submitted: false,
			end: null,
			droppedOn: null,
			stuck: false,
			pages,
			language: p.language,
			device: p.device,
			record: result(state),
			...o
		});
		/** Answer the visible questions (only `ids`, when given); `last`: a safe answer or blank. */
		const fill = (ids: readonly Id[] | null, last = false) => {
			const only = ids === null ? null : new Set(ids);
			const done = new Set<Id>();
			for (let guard = 0; guard < 500; guard++) {
				const id = visibleQuestions(state).find((x) => !done.has(x) && (only === null || only.has(x)));
				if (id === undefined) return;
				done.add(id);
				const q = plan.items[id] as QuestionItem;
				let value = draw(q, this.shapes.get(q), p, r, t);
				if (last) value = q.required ? (representative(q) as Value) : BLANK;
				// A blank is a question left untouched (or, on a retry, cleared).
				if (value === BLANK && (state.data.values[id] ?? null) === null) continue;
				wait(value === BLANK ? 1 : (THINK[q.type] ?? 5));
				state = answer(state, id, value);
			}
		};

		const maxSteps = 4 * Object.keys(plan.pages).length + 16;
		for (let step = 0; step < maxSteps; step++) {
			const v = view(state);
			if (v.status === 'ended') break;
			if (v.status === 'pending' && v.effect?.kind === 'quota') {
				wait(0.4);
				const reply = await ask({ do: 'quota', at: t, node: v.effect.nodeId });
				state = resolve(state, v.effect, reply.result === 'full' ? 'full' : 'open');
				await save();
				continue;
			}
			if (v.status !== 'page' || v.page === null) break;
			pages++;
			wait(1.5);
			if (spec.dropAt !== null && dropPage === null) {
				dropPage = 1 + Math.floor(spec.dropAt * Math.max(1, context(state).pagesEstimated));
			}
			if (dropPage !== null && pages >= dropPage) {
				// Leaves part-way through this page: some of it answered, saved as typed.
				const all = visibleQuestions(state);
				const some = all.slice(0, Math.floor(r() * all.length));
				const before = state;
				fill(some);
				if (state !== before) {
					wait(3); // the runtime's debounced save
					await save();
				}
				return outcome({ droppedOn: v.page });
			}
			fill(null);
			let out = next(state);
			for (let tries = 0; out.result.outcome === 'invalid' && tries < MAX_RETRIES; tries++) {
				state = out.state;
				wait(3);
				fill(Object.keys(state.data.errors), tries === MAX_RETRIES - 1);
				out = next(state);
			}
			if (out.result.outcome === 'invalid') {
				state = out.state;
				await save();
				return outcome({ droppedOn: v.page, stuck: true });
			}
			state = out.state;
			await save();
		}
		if (!state.data.ended) return outcome({ droppedOn: view(state).page, stuck: true });
		const record = result(state);
		wait(0.3);
		await ask({ do: 'submit', at: t, record });
		return outcome({ submitted: true, end: record.end, record });
	}
}
