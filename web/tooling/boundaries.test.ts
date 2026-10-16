/**
 * S3 acceptance: dependency-cruiser boundaries hold, and a deliberate violation fails.
 *
 * Violations are never written into the real tree. Each case builds a tiny fake web/
 * layout in a temp dir and runs depcruise there with the real config (rule paths are
 * relative to the cwd, so they apply unchanged).
 */
import { spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, it } from 'vitest';

const WEB = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const DEPCRUISE = join(WEB, 'node_modules', '.bin', 'depcruise');
const CONFIG = join(WEB, '.dependency-cruiser.cjs');

type Files = Record<string, string>;
const dirs: string[] = [];

function cruise(files: Files, cwd?: string) {
	let root = cwd;
	if (!root) {
		root = mkdtempSync(join(tmpdir(), 'osp-depcruise-'));
		dirs.push(root);
		for (const [path, body] of Object.entries(files)) {
			mkdirSync(dirname(join(root, path)), { recursive: true });
			writeFileSync(join(root, path), body);
		}
	}
	const args = ['builder/src', 'ui-components/src', 'api-client/src', '--config', CONFIG];
	// Default reporter: what `pnpm depcruise` (and so `make check`) runs; sets the exit code.
	const gate = spawnSync(DEPCRUISE, args, { cwd: root, encoding: 'utf8' });
	// JSON reporter (always exits 0): tells us which rules fired.
	const json = spawnSync(DEPCRUISE, [...args, '--output-type', 'json'], {
		cwd: root,
		encoding: 'utf8'
	});
	expect(gate.error).toBeUndefined();
	expect(json.error).toBeUndefined();
	const out = JSON.parse(json.stdout) as {
		summary: { violations: { rule: { name: string } }[] };
	};
	return { status: gate.status, rules: out.summary.violations.map((v) => v.rule.name) };
}

const base: Files = {
	'builder/src/main.ts': "import { x } from '../../api-client/src/index.ts';\nexport const y = x;\n",
	'ui-components/src/index.ts': 'export const ok = 1;\n',
	'api-client/src/index.ts': 'export const x = 1;\n'
};

afterEach(() => {
	for (const d of dirs.splice(0)) rmSync(d, { recursive: true, force: true });
});

describe('web boundaries (dependency-cruiser)', () => {
	it('the real workspace has no violations', () => {
		const { status, rules } = cruise({}, WEB);
		expect(rules).toEqual([]);
		expect(status).toBe(0);
	});

	it('a clean fake layout passes (builder -> api-client is allowed)', () => {
		const { status, rules } = cruise(base);
		expect(rules).toEqual([]);
		expect(status).toBe(0);
	});

	it.each([
		[
			'ui-components-not-to-api-client',
			'ui-components/src/bad.ts',
			"import { x } from '../../api-client/src/index.ts';\nexport const b = x;\n"
		],
		[
			// Imports used only in Svelte markup must still be seen.
			'ui-components-not-to-api-client',
			'ui-components/src/Bad.svelte',
			"<script lang=\"ts\">\n\timport { x } from '../../api-client/src/index.ts';\n</script>\n\n<p>{x}</p>\n"
		],
		[
			'nothing-imports-builder',
			'ui-components/src/bad.ts',
			"import { y } from '../../builder/src/main.ts';\nexport const b = y;\n"
		],
		[
			'api-client-is-a-leaf',
			'api-client/src/bad.ts',
			"import { ok } from '../../ui-components/src/index.ts';\nexport const b = ok;\n"
		],
		[
			'stay-inside-web',
			'builder/src/bad.ts',
			"import { s } from '../../../spikes/thing.ts';\nexport const b = s;\n"
		],
		[
			'not-to-unresolvable',
			'ui-components/src/bad.ts',
			"import { z } from 'no-such-package-anywhere';\nexport const b = z;\n"
		]
	])('violation %s (%s) fails', (rule, path, body) => {
		const files: Files = { ...base, [path]: body };
		if (rule === 'stay-inside-web') files['../spikes/thing.ts'] = 'export const s = 1;\n';
		const { status, rules } = cruise(files);
		expect(rules).toContain(rule);
		expect(status).not.toBe(0);
	});
});
