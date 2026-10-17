import { readdirSync, rmSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { defineConfig, devices } from '@playwright/test';

// Fixture harness (task R4): `make harness-quick` (touched fixtures, desktop Chromium) and
// `make harness-full` (every fixture × every device project, report in .build/harness/).
// server.py publishes every fixture on a fresh SQLite store and serves the built app.
const PORT = Number(process.env.OSP_HARNESS_PORT ?? 4392);

// One run, one directory: Playwright's output (incl. the per-worker trace artifacts) and the
// runtime build it serves. Two runs in one checkout (the Stop hook's `make check` beside an
// agent's own) used to share both: a starting run wiped the other's `.playwright-artifacts-N`,
// its context.close() failed on the trace (ENOENT), and the half-closed context failed the
// worker's next test ("apiRequestContext: Target page, context or browser has been closed").
// The port is unique per live run (the server binds it).
const RUNS = resolve(import.meta.dirname, '../../.build/harness/runs');
const RUN = join(RUNS, String(PORT));
const DIST = join(RUN, 'dist');

// Old runs' directories (traces of failures are kept a day), main process only.
if (!process.env.TEST_WORKER_INDEX) {
	try {
		for (const d of readdirSync(RUNS)) {
			const p = join(RUNS, d);
			if (p !== RUN && Date.now() - statSync(p).mtimeMs > 86_400_000) rmSync(p, { recursive: true, force: true });
		}
	} catch {
		// no runs yet
	}
}

export default defineConfig({
	testDir: 'tests',
	outputDir: join(RUN, 'test-results'),
	fullyParallel: true,
	workers: Number(process.env.OSP_HARNESS_WORKERS ?? 6),
	timeout: 120_000,
	expect: { timeout: 15_000 },
	forbidOnly: !!process.env.CI,
	reporter: [[process.env.CI ? 'github' : 'line'], ['./src/reporter.ts']],
	use: {
		baseURL: `http://127.0.0.1:${PORT}`,
		trace: 'retain-on-failure'
	},
	webServer: {
		command:
			`pnpm -C ../runtime exec vite build --logLevel warn --outDir ${JSON.stringify(DIST)} --emptyOutDir && ` +
			`cd ../.. && uv run --locked --with uvicorn==0.38.0 python web/harness/server.py --port ${PORT} --dist ${JSON.stringify(DIST)}`,
		url: `http://127.0.0.1:${PORT}/__harness/surveys`,
		reuseExistingServer: false,
		timeout: 240_000,
		env: { VIRTUAL_ENV: '' }
	},
	projects: [
		{ name: 'desktop-chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } } },
		{ name: 'iphone-se', use: { ...devices['iPhone SE'] } },
		{ name: 'pixel-7', use: { ...devices['Pixel 7'] } },
		{ name: 'desktop-firefox', use: { ...devices['Desktop Firefox'], viewport: { width: 1280, height: 800 } } }
	]
});
