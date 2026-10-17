/**
 * Node sidecar entry (bundled to dist/cli.js): reads `{ "plan": …, "options": … }` as JSON on
 * stdin, writes one JSON object on stdout and exits 0:
 *
 *   { "ok": true, "result": SimResult }
 *   { "ok": false, "error": { "code": "...", "message": "..." } }
 *
 * Exit code 2 only for a failure to even write that answer. Input over MAX_INPUT bytes is
 * refused. The caller (osp_runtime.sim_sidecar) adds the timeout and output limit.
 */

import { simulate, SimError } from './simulate.ts';

const MAX_INPUT = 8 * 1024 * 1024;

function reply(body: unknown): void {
	process.stdout.write(JSON.stringify(body) + '\n');
}

function fail(code: string, message: string): void {
	reply({ ok: false, error: { code, message: message.slice(0, 500) } });
}

async function readStdin(): Promise<string | null> {
	const chunks: Buffer[] = [];
	let size = 0;
	for await (const chunk of process.stdin) {
		const b = typeof chunk === 'string' ? Buffer.from(chunk) : (chunk as Buffer);
		size += b.length;
		if (size > MAX_INPUT) return null;
		chunks.push(b);
	}
	return Buffer.concat(chunks).toString('utf8');
}

async function main(): Promise<void> {
	const text = await readStdin();
	if (text === null) return fail('input.too_large', `input is larger than ${MAX_INPUT} bytes`);
	let input: unknown;
	try {
		input = JSON.parse(text);
	} catch {
		return fail('input.json', 'input is not JSON');
	}
	if (!input || typeof input !== 'object' || !('plan' in input) || !('options' in input)) {
		return fail('input.shape', 'input must be {"plan": ..., "options": ...}');
	}
	const { plan, options } = input as { plan: never; options: never };
	try {
		reply({ ok: true, result: simulate(plan, options) });
	} catch (e) {
		const code = e instanceof SimError ? e.code : typeof (e as { code?: unknown })?.code === 'string' ? (e as { code: string }).code : 'sim.failed';
		fail(code, e instanceof Error ? e.message : String(e));
	}
}

main().catch((e) => {
	try {
		fail('sim.crashed', e instanceof Error ? e.message : String(e));
	} catch {
		process.exitCode = 2;
	}
});
