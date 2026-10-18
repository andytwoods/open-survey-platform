/**
 * `@osp/ops`: every survey edit op of `python/osp-ops`, in TypeScript, with the same op
 * names, params, error codes and messages, resulting documents, JSON Patches, inverses and
 * transaction semantics. Proved equal by parity vectors (`make ops-parity`).
 *
 *     import { run, applyTransaction } from '@osp/ops';
 *     const res = run('set_property', survey, { target: 'q12', property: 'required', value: true }, env);
 *     res.ok, res.survey, res.inverse, res.patch, res.diagnostics
 *
 * The survey validator and the expression parser are injected (`OpsEnv.validator`); see
 * README.md for what the ops do without them. Pure: no DOM, no I/O, no clock, no randomness.
 */

// Area modules register their ops on import (one module per area, as in osp-ops).
import './doc.ts';
import './ops/question.ts';
import './ops/page.ts';
import './ops/property.ts';
import './ops/choice.ts';
import './ops/choiceList.ts';
import './ops/matrixRow.ts';
import './ops/condition.ts';
import './ops/flow.ts';
import './ops/survey.ts';
import './ops/misc.ts';
import './ops/questionType.ts';
import './ops/bank.ts';

export {
	DEFAULT_ENV,
	NO_VALIDATOR,
	OP_CODES,
	REGISTRY,
	enabled,
	invoke,
	run,
	type Diagnostic,
	type ExprDiagnostic,
	type Invocation,
	type OpResult,
	type OpSpec,
	type OpsEnv,
	type ParsedExpression,
	type Severity,
	type Validator
} from './registry.ts';
export { applyTransaction, MAX_OPS, type Draft, type TransactionResult } from './transaction.ts';
export { PatchError, apply as applyPatch, diff as diffPatch, toPointer, fromPointer, type Patch, type PatchOp } from './patch.ts';
export { same, deepCopy, type Json, type JsonObject } from './py.ts';
export { canonicalJson, fragmentChecksum, isRich, normaliseText, pipesOf, RESERVED_NAMES } from './spec.ts';
export { KEYWORDS } from './models.ts';

export { opCatalogue, opIds } from './catalogue.ts';
