import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import type { Page } from '@playwright/test';

// Serves /api/meta/expressions/{parse,print} from osp-api's own functions (expr_bridge.py),
// one long-lived Python process per Playwright worker.
const REPO = fileURLToPath(new URL('../../../', import.meta.url));
const SCRIPT = fileURLToPath(new URL('./expr_bridge.py', import.meta.url));

let proc: ChildProcessWithoutNullStreams | null = null;
let ready: Promise<void> | null = null;
const waiting: ((line: string) => void)[] = [];

/** Start the bridge (once per worker); resolves when it is ready to answer. */
export function startBridge(): Promise<void> {
	if (ready) return ready;
	const env = { ...process.env };
	delete env.VIRTUAL_ENV;
	// The workspace venv's interpreter directly (fast); `uv run` if it is not there yet.
	const python = join(REPO, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
	proc = existsSync(python)
		? spawn(python, [SCRIPT], { cwd: REPO, env })
		: spawn('uv', ['run', '--locked', 'python', SCRIPT], { cwd: REPO, env });
	const lines = createInterface({ input: proc.stdout });
	let stderr = '';
	proc.stderr.on('data', (d) => (stderr += String(d)));
	ready = new Promise((resolve, reject) => {
		proc!.on('exit', (code) => reject(new Error(`expr_bridge exited (${code}): ${stderr}`)));
		lines.once('line', () => {
			lines.on('line', (line) => waiting.shift()?.(line));
			resolve();
		});
	});
	return ready;
}

async function ask(path: 'parse' | 'print', body: unknown): Promise<unknown> {
	await startBridge();
	return new Promise((resolve) => {
		waiting.push((line) => resolve(JSON.parse(line)));
		proc!.stdin.write(JSON.stringify({ path, body }) + '\n');
	});
}

/** Route the expression endpoints to the bridge; returns the request log. */
export async function serveExpressions(page: Page) {
	const log: { path: string; body: Record<string, unknown> }[] = [];
	await page.route('**/api/meta/expressions/*', async (route) => {
		const path = route.request().url().endsWith('/print') ? 'print' : 'parse';
		const body = route.request().postDataJSON() as Record<string, unknown>;
		log.push({ path, body });
		await route.fulfill({ json: await ask(path, body) });
	});
	return log;
}
