/**
 * Regenerates the engine-produced ResponseRecords the data-export golden tests read.
 *
 *   make engine-fixtures
 *   node python/osp-targets/tests/data/dump_records.ts
 *
 * Every fixture script (fixtures/NN/scripts/*.json) is played through web/engine with the
 * fixture runner, and `result(state)` is written to records/<fixture>/<script>.json.
 * The records are committed, so `make check` does not need node to run the Python tests.
 */

import { mkdirSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { result } from '../../../../web/engine/src/index.ts';
import {
	FIXTURES,
	fixtureNames,
	loadJson,
	loadPlan,
	play,
	type Script
} from '../../../../web/engine/test/fixture-runner.ts';

const OUT = resolve(import.meta.dirname, 'records');
rmSync(OUT, { recursive: true, force: true });
let n = 0;
for (const name of fixtureNames()) {
	const { plan } = loadPlan(name);
	if (!plan) continue;
	const dir = join(FIXTURES, name, 'scripts');
	for (const file of readdirSync(dir).filter((f) => f.endsWith('.json')).sort()) {
		const script = loadJson<Script>(join(dir, file));
		let rec;
		try {
			rec = result(play(plan, script).state);
		} catch {
			continue; // a script the runner cannot play yet (engine-test reports it)
		}
		mkdirSync(join(OUT, name), { recursive: true });
		writeFileSync(join(OUT, name, file), JSON.stringify(rec, null, 1) + '\n');
		n++;
	}
}
console.log(`dump_records: ${n} records in ${OUT}`);
