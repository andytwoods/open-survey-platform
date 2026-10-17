/**
 * Diagnostics strip and export badges (builder-design §2, task B10): pure mapping from the
 * validator's diagnostics and an export check's diagnostics to strip items, counts and the
 * badges shown on cards. No survey logic: everything comes from the server; this only
 * works out *where* a JSON pointer lands (which block, page or question, which property).
 */
import { pointerSegments } from '../json/source';

export type TargetId = 'xlsform' | 'lss';
export type TargetChoice = TargetId | 'none';

export const TARGET_OPTIONS: { value: TargetChoice; label: string }[] = [
	{ value: 'none', label: 'None' },
	{ value: 'xlsform', label: 'XLSForm' },
	{ value: 'lss', label: 'LimeSurvey' }
];

export const targetLabel = (t: TargetChoice) => TARGET_OPTIONS.find((o) => o.value === t)?.label ?? t;

/** A validator diagnostic (`osp-spec`), as the API sends it. */
export interface ValidationDiagnostic {
	severity: 'error' | 'warning' | 'info';
	code: string;
	message: string;
	pointer: string;
}

/** An export diagnostic (`osp-targets`), as `GET …/export-check` sends it. */
export interface ExportDiagnostic {
	target: string;
	severity: 'info' | 'warning' | 'loss' | 'error';
	code: string;
	feature: string;
	level: 'native' | 'lowered' | 'approximated' | 'unsupported' | null;
	pointer: string;
	message: string;
}

/** Id the selection uses for the survey itself (survey-level properties). */
export const SURVEY_ID = '#survey';

export interface Owner {
	/** Block, page or question id; `SURVEY_ID` for anything outside the blocks. */
	id: string;
	type: 'survey' | 'block' | 'page' | 'question';
	/** Candidate property-panel keys, most specific first (e.g. `settings.backNavigation`). */
	properties: string[];
}

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v);

function propertyKeys(rest: string[]): string[] {
	// Drop array indices and language keys from the tail: the panel edits whole properties.
	const out: string[] = [];
	for (let n = rest.length; n > 0; n--) out.push(rest.slice(0, n).join('.'));
	return out;
}

/**
 * The innermost block, page or question a pointer lands in, and the property path below
 * it. Unknown shapes fall back to the survey.
 */
export function ownerOf(survey: unknown, pointer: string): Owner {
	const seg = pointerSegments(pointer);
	const fallback: Owner = { id: SURVEY_ID, type: 'survey', properties: propertyKeys(seg) };
	if (!isObj(survey) || seg[0] !== 'blocks' || seg.length < 2) return fallback;
	const blocks = Array.isArray(survey.blocks) ? survey.blocks : [];
	const block = blocks[Number(seg[1])];
	if (!isObj(block) || typeof block.id !== 'string') return fallback;
	let owner: Owner = { id: block.id, type: 'block', properties: propertyKeys(seg.slice(2)) };
	if (seg[2] !== 'pages' || seg.length < 4) return owner;
	const page = (Array.isArray(block.pages) ? block.pages : [])[Number(seg[3])];
	if (!isObj(page) || typeof page.id !== 'string') return owner;
	owner = { id: page.id, type: 'page', properties: propertyKeys(seg.slice(4)) };
	if (seg[4] !== 'items' || seg.length < 6) return owner;
	const item = (Array.isArray(page.items) ? page.items : [])[Number(seg[5])];
	if (!isObj(item) || typeof item.id !== 'string') return owner;
	return { id: item.id, type: 'question', properties: propertyKeys(seg.slice(6)) };
}

// --- export badges ---------------------------------------------------------------------

export type BadgeLevel = 'approximated' | 'unsupported';

export interface ExportBadge {
	level: BadgeLevel;
	/** Visible text, e.g. "Unsupported in LimeSurvey". */
	label: string;
	/** Why: one line per diagnostic, for the tooltip and screen readers. */
	reasons: string[];
	/** Where the first diagnostic points (for "go to property"). */
	pointer: string;
	features: string[];
}

const BADGE_ORDER: BadgeLevel[] = ['unsupported', 'approximated'];

/** Does this export diagnostic deserve a badge (behaviour lost or changed)? */
export const isBadgeLevel = (level: ExportDiagnostic['level']): level is BadgeLevel =>
	level === 'approximated' || level === 'unsupported';

/** The reason text shown in the tooltip: the capability note, without the restated key. */
export function reasonOf(d: ExportDiagnostic): string {
	const m = /^\S+ is (?:approximated|unsupported) in [^:]+: (.*)$/s.exec(d.message);
	return m ? m[1] : d.message;
}

/**
 * Badges per block/page/question id (`SURVEY_ID` for survey-level ones): one per level,
 * unsupported first, collecting every reason. Lowered/native features get no badge.
 */
export function exportBadges(
	survey: unknown,
	diagnostics: readonly ExportDiagnostic[],
	target: TargetChoice
): Map<string, ExportBadge[]> {
	const name = targetLabel(target);
	const byOwner = new Map<string, Map<BadgeLevel, ExportBadge>>();
	for (const d of diagnostics) {
		if (!isBadgeLevel(d.level)) continue;
		const { id } = ownerOf(survey, d.pointer);
		let levels = byOwner.get(id);
		if (!levels) byOwner.set(id, (levels = new Map()));
		let badge = levels.get(d.level);
		if (!badge) {
			badge = {
				level: d.level,
				label: `${d.level === 'unsupported' ? 'Unsupported' : 'Approximated'} in ${name}`,
				reasons: [],
				pointer: d.pointer,
				features: []
			};
			levels.set(d.level, badge);
		}
		const reason = reasonOf(d);
		if (!badge.reasons.includes(reason)) badge.reasons.push(reason);
		if (!badge.features.includes(d.feature)) badge.features.push(d.feature);
	}
	const out = new Map<string, ExportBadge[]>();
	for (const [id, levels] of byOwner) {
		out.set(
			id,
			BADGE_ORDER.flatMap((l) => (levels.has(l) ? [levels.get(l)!] : []))
		);
	}
	return out;
}

// --- strip items and counts ------------------------------------------------------------

export type ItemKind = 'error' | 'warning' | 'info' | 'export';

export interface StripItem {
	key: string;
	kind: ItemKind;
	/** For export items: the capability level, or "error" when nothing can be exported. */
	level?: BadgeLevel | 'error';
	message: string;
	code: string;
	pointer: string;
	owner: Owner;
	/** Short "where" text: the owner's label and property. */
	where: string;
}

export interface Counts {
	errors: number;
	warnings: number;
	exportIssues: number;
}

function label(owner: Owner): string {
	if (owner.type === 'survey') return 'Survey';
	const kind = owner.type === 'question' ? 'Question' : owner.type === 'page' ? 'Page' : 'Block';
	return `${kind} ${owner.id}`;
}

/** Strip items: validation errors, then warnings, then export issues, then info. */
export function stripItems(
	survey: unknown,
	validation: readonly ValidationDiagnostic[],
	exportDiagnostics: readonly ExportDiagnostic[]
): StripItem[] {
	const items: StripItem[] = [];
	validation.forEach((d, i) => {
		const owner = ownerOf(survey, d.pointer ?? '');
		const prop = owner.properties[0];
		items.push({
			key: `v${i}`,
			kind: d.severity === 'error' ? 'error' : d.severity === 'warning' ? 'warning' : 'info',
			message: d.message,
			code: d.code,
			pointer: d.pointer ?? '',
			owner,
			where: prop ? `${label(owner)} · ${prop}` : label(owner)
		});
	});
	exportDiagnostics.forEach((d, i) => {
		const level = d.severity === 'error' ? 'error' : isBadgeLevel(d.level) ? d.level : null;
		if (!level) return;
		const owner = ownerOf(survey, d.pointer);
		const prop = owner.properties[0];
		items.push({
			key: `x${i}`,
			kind: 'export',
			level,
			message: level === 'error' ? d.message : reasonOf(d),
			code: d.feature || d.code,
			pointer: d.pointer,
			owner,
			where: d.pointer ? (prop ? `${label(owner)} · ${prop}` : label(owner)) : 'Whole survey'
		});
	});
	const rank: Record<ItemKind, number> = { error: 0, warning: 1, export: 2, info: 3 };
	return items.sort((a, b) => rank[a.kind] - rank[b.kind]);
}

export function countItems(items: readonly StripItem[]): Counts {
	let errors = 0;
	let warnings = 0;
	let exportIssues = 0;
	for (const i of items) {
		if (i.kind === 'error') errors++;
		else if (i.kind === 'warning') warnings++;
		else if (i.kind === 'export') exportIssues++;
	}
	return { errors, warnings, exportIssues };
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** "2 errors, 1 warning, 3 export issues (LimeSurvey)" — what the live region says. */
export function countsText(c: Counts, target: TargetChoice): string {
	const parts = [plural(c.errors, 'error'), plural(c.warnings, 'warning')];
	if (target !== 'none') parts.push(`${plural(c.exportIssues, 'export issue')} (${targetLabel(target)})`);
	return parts.join(', ');
}
