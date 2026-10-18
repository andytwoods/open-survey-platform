/**
 * @osp/spec: the osp-spec validator in TypeScript (planning/client-edits.md, task CE4).
 *
 * `validate(doc)` returns exactly the diagnostics `osp_spec.validate(doc)` returns (code,
 * severity, message, pointer, in the same order), for instant feedback in the builder and
 * for the serverless demo. The server's validator stays authoritative on save; parity
 * vectors (`make spec-test`) keep the two equal. Differences: README.md.
 */

export { CODES, type Diagnostic, hasErrors, pointer, type Severity } from './diagnostics.ts';
export { BUILTIN_PIPES, ENDING_PIPES, parse, validate } from './validate.ts';
export { SPEC_VERSION } from './model.ts';
