/**
 * Shapes of the property schema served at `GET /api/meta/property-schemas`
 * (`osp_spec.property_schema.property_schemas_json()`, builder-design §1), plus the few
 * things the property panel emits. Display-only: no survey semantics live here.
 */

/** A `{language: text}` map, as the schema writes labels and help. */
export type LocalisedText = Record<string, string>;

export type PropertyKind =
	| 'text'
	| 'richtext'
	| 'number'
	| 'bool'
	| 'enum'
	| 'choicelist'
	| 'condition'
	| 'expression';

export type Entity = 'question' | 'page' | 'block' | 'survey';

export interface EnumOption {
	value: string;
	label: LocalisedText;
}

export interface PropertySpec {
	kind: PropertyKind;
	label: LocalisedText;
	group: string;
	required?: boolean;
	translatable?: boolean;
	default?: unknown;
	help?: LocalisedText;
	options?: EnumOption[];
	/** Dotted path (from the survey root) of a list whose items are the options. */
	optionsFrom?: string;
}

export interface TypeSchema {
	type: string;
	entity: Entity;
	family?: string;
	label: LocalisedText;
	icon?: string;
	/** Keys are model fields; dotted keys (`metadata.title`) reach into nested objects. */
	properties: Record<string, PropertySpec>;
	hidden?: Record<string, string>;
}

export interface PropertySchemasDoc {
	kinds: PropertyKind[];
	families: string[];
	groups: string[];
	schemas: TypeSchema[];
}

/** An `osp-spec` diagnostic (RFC 6901 `pointer` into the survey document). */
export interface PanelDiagnostic {
	severity: 'error' | 'warning' | 'info' | string;
	code: string;
	message: string;
	pointer: string;
}

/** `set_property` params (see `GET /api/meta/ops`). */
export interface SetPropertyParams {
	target: string;
	property: string;
	value?: unknown;
	unset?: boolean;
}

/** One op invocation, as the op client (B2) submits it. */
export interface SetPropertyOp {
	op: 'set_property';
	params: SetPropertyParams;
}

/** Asked of the shell when a choicelist / condition / expression field's button is used. */
export interface OpenEditorRequest {
	kind: PropertyKind;
	/** The schema key, e.g. `choices` or `showIf`. */
	path: string;
	/** `set_property` target and property for the editor's own ops. */
	target: string;
	property: string;
	value: unknown;
}
