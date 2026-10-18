/**
 * Data the question cards read (builder-design §2). Cards are store-independent: B2 passes
 * plain JSON straight from the survey document and the property-schema endpoint.
 *
 * Shapes mirror `osp-spec` (model.py, properties/*.yaml) loosely and every field is
 * optional, because a card must render *something* for any input (golden rule 3).
 */
import type { RichText } from '@osp/engine';
import type { Snippet } from 'svelte';
import type { HTMLButtonAttributes } from 'svelte/elements';

/**
 * Translatable text (osp-spec `Text`): a plain string, a rich tree (planning/rich-text.md
 * §3) or a `{language: value}` map of either.
 */
export type SpecText = string | RichText | Readonly<Record<string, string | RichText>>;

/** One `osp-expr` AST node (JSON, `kind` discriminator). Unknown kinds are tolerated. */
export interface ExprNode {
	kind: string;
	[field: string]: unknown;
}

export interface SpecChoice {
	value: string | number;
	label: SpecText;
}

export interface SpecChoiceList {
	id: string;
	choices: readonly SpecChoice[];
}

/** One matrix row (osp-spec `MatrixRow`): its variable is `<matrix id>_<row id>`. */
export interface SpecMatrixRow {
	id: string;
	label: SpecText;
	required?: boolean | null;
}

/**
 * A question as stored in the survey. `rows` is a matrix's (osp-spec `MatrixQuestion`);
 * `min`/`max`/`step`/`valueType`/`minLabel`/`maxLabel` a slider's (`SliderQuestion`, where
 * numbers may also be decimal text).
 */
export interface CardQuestion {
	id: string;
	type: string;
	label?: SpecText;
	help?: SpecText | null;
	required?: boolean;
	showIf?: ExprNode | null;
	constraint?: ExprNode | null;
	constraintMessage?: SpecText | null;
	choices?: readonly SpecChoice[] | null;
	choiceList?: string | null;
	choiceOrder?: 'fixed' | 'shuffle' | string;
	rows?: readonly SpecMatrixRow[] | null;
	min?: number | string;
	max?: number | string;
	step?: number | string;
	valueType?: 'integer' | 'decimal' | string;
	minLabel?: SpecText | null;
	maxLabel?: SpecText | null;
	[field: string]: unknown;
}

export const FAMILIES = ['choice', 'text', 'number', 'matrix', 'scale', 'note'] as const;
export type CardFamily = (typeof FAMILIES)[number];

/** One question type's property schema (osp_spec/properties/<type>.yaml, as JSON). */
export interface PropertySchemaData {
	type: string;
	entity?: string;
	family?: string;
	label?: SpecText;
	icon?: string;
	properties?: Readonly<Record<string, unknown>>;
	hidden?: Readonly<Record<string, unknown>>;
}

/** A validator diagnostic already scoped to this question by the caller. */
export interface CardDiagnostic {
	severity: 'error' | 'warning' | 'info';
	code: string;
	message: string;
	pointer?: string;
}

export type BadgeKind = 'showIf' | 'shuffle' | 'validation' | 'errors' | 'warnings';

export interface Badge {
	kind: BadgeKind;
	/** Short visible text, e.g. "Show if". */
	label: string;
	/** Condition text form, or a count summary. */
	detail?: string;
	tone: 'neutral' | 'danger' | 'warning';
}

/**
 * Props every card takes. `family` may be omitted: the dispatcher works it out from the
 * schema or type. `class` styles the card root; other attributes (e.g. `id`,
 * `data-pane-focus`) land on the card's select button, its focus target.
 */
export type CardProps = {
	question: CardQuestion;
	family?: string | null;
	schema?: PropertySchemaData | null;
	selected?: boolean;
	diagnostics?: readonly CardDiagnostic[] | null;
	/** Language to show translatable text in (default English, then the first available). */
	lang?: string;
	/** The survey's shared choice lists, so a `choiceList` reference can be previewed. */
	choiceLists?: readonly SpecChoiceList[];
	/** Click or Enter on the card. */
	onselect?: (id: string) => void;
	/**
	 * The error or warning count badge was clicked (B18). When given, those badges are
	 * buttons, so the caller can go to the property the first such diagnostic is about.
	 */
	ondiagnostic?: (severity: 'error' | 'warning') => void;
	/** Slot for export-warning badges (B10): render `<li>` items. */
	exportBadges?: Snippet;
} & Omit<HTMLButtonAttributes, 'children' | 'onselect' | 'onclick' | 'type'>;
