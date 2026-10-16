import { defineConfig, devices } from '@playwright/test';

// Fixture harness (task R4): `make harness-quick` (touched fixtures, desktop Chromium) and
// `make harness-full` (every fixture × every device project, report in .build/harness/).
// server.py publishes every fixture on a fresh SQLite store and serves the built app.
const PORT = Number(process.env.OSP_HARNESS_PORT ?? 4392);

export default defineConfig({
	testDir: 'tests',
	outputDir: '../../.build/harness/test-results',
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
			`pnpm -C ../runtime exec vite build --logLevel warn && ` +
			`cd ../.. && uv run --locked --with uvicorn==0.38.0 python web/harness/server.py --port ${PORT}`,
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
