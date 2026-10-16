/** Every compiled fixture plan validates against contract/runtime-plan.schema.json. */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import Ajv2020 from 'ajv/dist/2020.js';
import { describe, expect, it } from 'vitest';
import { checkPlan, planChecksum } from '../src/index.ts';
import { REPO, fixtureNames, loadPlan } from './fixture-runner.ts';
import { makePlan, q } from './helpers.ts';

const schema = JSON.parse(readFileSync(join(REPO, 'contract/runtime-plan.schema.json'), 'utf8'));
const validate = new Ajv2020({ allErrors: true, strict: false }).compile(schema);

describe('runtime plan schema', () => {
	for (const name of fixtureNames()) {
		it(`${name} plan is valid and its checksum matches the engine's`, () => {
			const { plan, error } = loadPlan(name);
			expect(error).toBeUndefined();
			const ok = validate(plan);
			expect(validate.errors ?? []).toEqual([]);
			expect(ok).toBe(true);
			expect(planChecksum(plan!)).toBe(plan!.checksum); // Python and TS canonical JSON agree
			expect(() => checkPlan(plan!)).not.toThrow();
		});
	}

	it('rejects a malformed plan', () => {
		const plan = makePlan({ pages: { p1: [q('a', 'text')] } }) as unknown as Record<string, unknown>;
		expect(validate(plan)).toBe(true);
		expect(validate({ ...plan, planVersion: 'osp-runtime-plan/2' })).toBe(false);
		expect(validate({ ...plan, items: { a: { id: 'a', type: 'note', page: 'p1', label: {}, required: true } } })).toBe(
			false
		);
	});
});
