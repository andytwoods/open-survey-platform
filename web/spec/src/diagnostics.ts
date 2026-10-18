/** Validator diagnostics (osp_spec.diagnostics): severity, stable code, message, RFC 6901 pointer. */

export type Severity = 'error' | 'warning' | 'info';

export interface Diagnostic {
	severity: Severity;
	code: string;
	message: string;
	pointer: string; // RFC 6901, "" is the document root
}

/** Every code the validator can emit, with its severity (osp_spec.diagnostics.CODES). */
export const CODES: Readonly<Record<string, Severity>> = {
	'schema.type': 'error',
	'schema.missing': 'error',
	'schema.extra': 'error',
	'schema.enum': 'error',
	'schema.pattern': 'error',
	'schema.value': 'error',
	'spec.unsupported_version': 'error',
	'id.duplicate': 'error',
	'id.reserved': 'error',
	'name.duplicate': 'error',
	'name.case_collision': 'error',
	'name.reserved': 'error',
	'lang.duplicate': 'error',
	'lang.unknown_default': 'error',
	'text.unknown_language': 'error',
	'text.missing_translation': 'warning',
	'text.too_long': 'error',
	'text.too_many_blocks': 'error',
	'text.block_not_allowed': 'error',
	'link.scheme': 'error',
	'link.empty': 'error',
	'choice.source': 'error',
	'choice.duplicate_value': 'error',
	'choice.invalid_value': 'error',
	'choice.mixed_types': 'warning',
	'choicelist.unused': 'info',
	'ref.unknown': 'error',
	'ref.unknown_block': 'error',
	'ref.unknown_choice_list': 'error',
	'ref.unknown_quota': 'error',
	'ref.unknown_variable': 'error',
	'ref.no_value': 'error',
	'ref.unknown_choice_code': 'warning',
	'ref.self': 'error',
	'ref.forward': 'error',
	'ref.not_in_flow': 'warning',
	'ref.randomised_sibling': 'warning',
	'ref.other_branch': 'warning',
	'ref.cycle': 'error',
	'pipe.invalid': 'error',
	'expr.type': 'error',
	'flow.empty': 'warning',
	'flow.unreachable': 'warning',
	'flow.block_reused': 'error',
	'flow.empty_branch': 'warning',
	'flow.pick_too_large': 'error',
	'flow.assign_wrong_kind': 'error',
	'flow.variable_reassigned': 'error',
	'block.unused': 'warning',
	'quota.unused': 'warning',
	'question.bounds': 'error',
	'question.slider': 'error',
	'matrix.duplicate_row': 'error',
	'matrix.row_id': 'error',
	'settings.retention': 'error',
	'consent.pipe': 'error',
	'consent.outcome': 'error',
	'ending.unreachable': 'warning',
	'ending.declined_summary': 'error',
	'redirect.template': 'error',
	'redirect.template_clash': 'error',
	'redirect.unknown_template': 'error',
	'redirect.params': 'error',
	'redirect.param_literal': 'error',
	'redirect.param_question': 'warning',
	'redirect.immediate': 'warning',
	'external.unknown_template': 'error',
	'external.params': 'error',
	'external.param_literal': 'error',
	'external.param_question': 'warning',
	'external.reserved_param': 'error',
	'external.return_target': 'error',
	'hooks.unknown_ref': 'error',
	'hooks.write_target': 'error',
	'hooks.redirect': 'error',
	'hooks.parent_origin': 'error',
	'publish.retention_required': 'error',
	'publish.consent_missing': 'warning',
	'variable.cycle': 'error',
	'variable.never_assigned': 'warning',
	'variable.duplicate_level': 'error',
	'variable.default_type': 'error',
	'internal.error': 'error'
};

export function make(code: string, pointer: string, message: string): Diagnostic {
	const severity = CODES[code];
	if (severity === undefined) throw new Error(`unknown diagnostic code ${code}`);
	return { severity, code, message, pointer };
}

/** An RFC 6901 pointer from path parts. */
export function pointer(...parts: Array<string | number>): string {
	return parts.map((p) => '/' + String(p).replaceAll('~', '~0').replaceAll('/', '~1')).join('');
}

export function hasErrors(diagnostics: Diagnostic[]): boolean {
	return diagnostics.some((d) => d.severity === 'error');
}
