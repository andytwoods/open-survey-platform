/**
 * Node entry for `osp-cli fake-responses` (task DS1; bundled to dist/fake.js). A
 * conversation of JSON lines on stdin/stdout, so each fake participant can wait for the
 * server's answers (session start, quota checks) like the participant app does:
 *
 *   → {"op":"init","plan":…,"seed":1}            ← {"ok":true}
 *   → {"op":"run","spec":ParticipantSpec}        ← {"ask":Ask}   (zero or more, each answered by)
 *   → {"reply":AskReply}                          …
 *                                                ← {"done":ParticipantOutcome}
 *   any failure                                  ← {"error":{"code","message"}}
 *
 * Dev tooling only: the server never runs this.
 */

import { createInterface } from 'node:readline';
import { FakeParticipants, type AskReply, type ParticipantSpec } from './fake.ts';

function send(body: unknown): void {
	process.stdout.write(JSON.stringify(body) + '\n');
}

function fail(code: string, e: unknown): void {
	send({ error: { code, message: (e instanceof Error ? e.message : String(e)).slice(0, 500) } });
}

const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
const queue: string[] = [];
let waiter: ((line: string | null) => void) | null = null;
let closed = false;
lines.on('line', (line) => {
	if (waiter) {
		const w = waiter;
		waiter = null;
		w(line);
	} else queue.push(line);
});
lines.on('close', () => {
	closed = true;
	if (waiter) waiter(null);
});

function readLine(): Promise<string | null> {
	const line = queue.shift();
	if (line !== undefined) return Promise.resolve(line);
	if (closed) return Promise.resolve(null);
	return new Promise((res) => (waiter = res));
}

async function readJson(): Promise<Record<string, unknown> | null> {
	const line = await readLine();
	if (line === null) return null;
	const v = JSON.parse(line) as unknown;
	if (!v || typeof v !== 'object') throw new Error('each line must be a JSON object');
	return v as Record<string, unknown>;
}

async function main(): Promise<void> {
	let fakes: FakeParticipants | null = null;
	for (;;) {
		const msg = await readJson();
		if (msg === null) return;
		try {
			if (msg['op'] === 'init') {
				fakes = new FakeParticipants(msg['plan'] as never, Number(msg['seed'] ?? 1));
				send({ ok: true });
			} else if (msg['op'] === 'run') {
				if (!fakes) throw new Error('init first');
				const outcome = await fakes.run(msg['spec'] as ParticipantSpec, async (ask) => {
					send({ ask });
					const reply = await readJson();
					if (reply === null) throw new Error('stdin closed while waiting for a reply');
					return (reply['reply'] ?? {}) as AskReply;
				});
				send({ done: outcome });
			} else throw new Error(`unknown op ${String(msg['op'])}`);
		} catch (e) {
			const code = typeof (e as { code?: unknown })?.code === 'string' ? (e as { code: string }).code : 'fake.failed';
			fail(code, e);
		}
	}
}

main().catch((e) => {
	try {
		fail('fake.crashed', e);
	} catch {
		process.exitCode = 2;
	}
});
