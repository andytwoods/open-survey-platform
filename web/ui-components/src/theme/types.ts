/**
 * TypeScript types for a survey theme (osp_spec.theme.Theme, runtime-design §6a).
 *
 * Hand-written: the value lists below are the single TS source of each enum, and
 * theme-bridge.test.ts (builder dev route) checks them, the field names and the required
 * fields against the committed JSON Schema in ./generated/theme.schema.json.
 */

export const THEME_VERSION = 'osp-theme/0.1';
export const PRESET_IDS = ['clean', 'warm', 'high-contrast', 'dark', 'compact'] as const;
export const FONT_IDS = ['system-sans', 'system-serif', 'system-rounded'] as const;
export const DENSITIES = ['comfortable', 'compact'] as const;
export const BUTTON_STYLES = ['filled', 'outline'] as const;
export const CHOICE_STYLES = ['list', 'cards', 'buttons'] as const;
export const THEME_MODES = ['light', 'dark', 'auto'] as const;
export const PALETTE_FIELDS = [
	'accent',
	'background',
	'surface',
	'text',
	'muted',
	'error',
	'focus'
] as const;

export type PresetId = (typeof PRESET_IDS)[number];
export type FontId = (typeof FONT_IDS)[number];
export type Density = (typeof DENSITIES)[number];
export type ButtonStyle = (typeof BUTTON_STYLES)[number];
export type ChoiceStyle = (typeof CHOICE_STYLES)[number];
export type ThemeMode = (typeof THEME_MODES)[number];
/** A mode the page can actually show (`auto` resolves to one of these). */
export type Mode = 'light' | 'dark';
export type PaletteField = (typeof PALETTE_FIELDS)[number];

/** `#rrggbb` */
export type HexColour = string;
/** A plain string or a `{language: string}` map, as in the survey model. */
export type Text = string | Record<string, string>;

export type Palette = Record<PaletteField, HexColour>;

export interface Theme {
	themeVersion?: typeof THEME_VERSION;
	preset?: PresetId | null;
	colours: { light: Palette; dark: Palette };
	logoAssetId?: string | null;
	headerText?: Text | null;
	font?: FontId;
	/** px, 12–32; the guard requires >= 16 (input font size). */
	baseSize?: number;
	lineSpacing?: number;
	/** px, 0–32 */
	radius?: number;
	density?: Density;
	buttonStyle?: ButtonStyle;
	choiceStyle?: ChoiceStyle;
	mode?: ThemeMode;
}

/** Every top-level field of {@link Theme}, for the schema check. */
export const THEME_FIELDS = [
	'themeVersion',
	'preset',
	'colours',
	'logoAssetId',
	'headerText',
	'font',
	'baseSize',
	'lineSpacing',
	'radius',
	'density',
	'buttonStyle',
	'choiceStyle',
	'mode'
] as const satisfies readonly (keyof Theme)[];

/** Defaults, identical to the pydantic model's. */
export const THEME_DEFAULTS = {
	font: 'system-sans',
	baseSize: 16,
	lineSpacing: 1.5,
	radius: 6,
	density: 'comfortable',
	buttonStyle: 'filled',
	choiceStyle: 'list',
	mode: 'auto'
} as const satisfies Partial<Theme>;

export interface ThemePreset {
	id: PresetId;
	name: string;
	theme: Theme;
}
