/**
 * Props contract for the participant question widgets (runtime-design §6, §8).
 *
 * Every widget takes the same base props (`QuestionProps<V>`) plus a few widget-specific
 * ones, and reports edits through `onchange(value)`. Widgets hold no survey logic: they
 * never decide relevance, required-ness or validity beyond the *format* of what was typed
 * (e.g. "12,5" is not an integer, 31/02 is not a date). The engine's `PageView` maps onto
 * these props one-to-one.
 *
 * Values are always plain JSON:
 *   integer / decimal   string | null   canonical, "." separator, exact ("3.50" stays "3.50")
 *   text                string
 *   single choice       string | null   the choice `value`
 *   multi choice        string[]        choice values, in choice order
 *   date                string | null   ISO "YYYY-MM-DD"
 *   matrix              Record<rowValue, columnValue | null>
 *   slider              number | null   null until the participant touches it
 * `null` means unanswered, or typed but not (yet) in a valid format; the widget then shows
 * its own format message until the engine supplies an `error`.
 */

/**
 * One run of display text (planning/rich-text.md §7). `text` is plain text, already
 * resolved by the engine (piping included); widgets render it as a text node and never as
 * HTML. `href` makes the run a link (an absolute https URL, opened in a new tab).
 */
export interface TextSegment {
	text: string;
	strong?: boolean;
	em?: boolean;
	/** BCP 47 tag when this run is in a different language from the question. */
	lang?: string;
	/** An https link; adjacent runs with the same href are one link. */
	href?: string;
}

/** A line break inside a run of inline text. */
export interface TextBreak {
	br: true;
}

export type InlineNode = TextSegment | TextBreak;

/** Inline display text: a plain string, or runs and breaks. */
export type InlineText = string | readonly InlineNode[];

/**
 * One block of display text: a paragraph, a heading (1–3, rendered as h3–h5 under the
 * page's h2) or a single-level bulleted / numbered list.
 */
export type TextBlock =
	| { type: 'p'; content: readonly InlineNode[] }
	| { type: 'h'; level: 1 | 2 | 3; content: readonly InlineNode[] }
	| { type: 'ul' | 'ol'; items: readonly (readonly InlineNode[])[] };

/** Display text: a plain string, inline runs, or blocks (RichText renders any of them). */
export type Text = InlineText | readonly TextBlock[];

export interface Choice {
	/** Stored value. Unique within the question. */
	value: string;
	label: Text;
	/** Optional secondary line under the label. */
	help?: Text;
	disabled?: boolean;
}

/** Base props shared by every question widget. */
export interface QuestionProps<V> {
	/** Unique on the page; prefixes every DOM id the widget creates. */
	id: string;
	label: Text;
	help?: Text;
	required?: boolean;
	value: V;
	/** Engine validation message. Shown inline and linked with aria-describedby. */
	error?: string | null;
	disabled?: boolean;
	/** Choices for choice widgets; the columns (scale points) for Matrix. */
	choices?: readonly Choice[];
	/** BCP 47 language of the question. Drives separators, date field order and direction. */
	lang?: string;
	/** The question just appeared because of an earlier answer: announce it once. */
	revealed?: boolean;
	/** Participant-facing UI strings (field labels, format errors). English by default. */
	messages?: Partial<WidgetMessages>;
	onchange?: (value: V) => void;
}

export type ChoiceStyle = 'list' | 'cards' | 'buttons';

export type IntegerValue = string | null;
export type DecimalValue = string | null;
export type TextValue = string;
export type SingleChoiceValue = string | null;
export type MultiChoiceValue = string[];
export type DateValue = string | null;
export type MatrixValue = Record<string, string | null>;
export type SliderValue = number | null;

/**
 * `min` only picks the on-screen keyboard: a negative `min` needs a keyboard with a minus
 * sign. Range checks are constraints, so the engine reports them through `error`.
 */
export interface IntegerInputProps extends QuestionProps<IntegerValue> {
	min?: number;
}

export interface DecimalInputProps extends QuestionProps<DecimalValue> {
	min?: number;
}

export interface TextInputProps extends QuestionProps<TextValue> {
	/** Long text: an auto-growing textarea. */
	multiline?: boolean;
	maxLength?: number;
	/** Hint for the browser's autofill (e.g. "off", "postal-code"). */
	autocomplete?: string;
}

export interface SingleChoiceProps extends QuestionProps<SingleChoiceValue> {
	choices: readonly Choice[];
	choiceStyle?: ChoiceStyle;
}

export interface MultiChoiceProps extends QuestionProps<MultiChoiceValue> {
	choices: readonly Choice[];
	choiceStyle?: ChoiceStyle;
}

/** Date ranges are constraints (engine); the widget only rejects dates that don't exist. */
export type DateInputProps = QuestionProps<DateValue>;

export type NoteProps = Omit<QuestionProps<null>, 'value' | 'required' | 'error' | 'onchange'> & {
	value?: null;
};

export interface MatrixProps extends QuestionProps<MatrixValue> {
	/** The sub-questions (one radio group each). */
	rows: readonly Choice[];
	/** The scale points, shared by every row. */
	choices: readonly Choice[];
}

export interface SliderProps extends QuestionProps<SliderValue> {
	min: number;
	max: number;
	step?: number;
	/** Text under the two ends of the track. */
	minLabel?: Text;
	maxLabel?: Text;
}

/** Participant-facing strings the widgets render themselves. `{x}` are placeholders. */
export interface WidgetMessages {
	required: string;
	day: string;
	month: string;
	year: string;
	notAnswered: string;
	sliderValue: string;
	sliderTypeValue: string;
	invalidInteger: string;
	invalidDecimal: string;
	/** Slider's typed alternative outside the track. `{min}` / `{max}` are replaced. */
	outOfRange: string;
	incompleteDate: string;
	invalidDate: string;
	/** Announced once when a question is revealed. `{label}` is replaced. */
	revealed: string;
	/** Visually hidden suffix of a link in researcher text (links open in a new tab). */
	opensInNewTab: string;
}
