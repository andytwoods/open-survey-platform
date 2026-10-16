import { defineConfig, devices } from '@playwright/test';

// The hooks adversarial gate (runtime-design.md §7a): `make hooks-e2e`. Real Chromium and
// WebKit. The server logs every request that is not a harness file (egress canary).
const PORT = 4417;

export default defineConfig({
	testDir: 'e2e',
	// One server-side egress log: tests run one at a time so a hit is attributable.
	fullyParallel: false,
	workers: 1,
	forbidOnly: !!process.env.CI,
	reporter: process.env.CI ? 'github' : 'list',
	timeout: 60_000,
	use: {
		baseURL: `http://127.0.0.1:${PORT}`,
		trace: 'retain-on-failure'
	},
	webServer: {
		command: 'vite build --config e2e/vite.config.ts && node e2e/server.mjs',
		url: `http://127.0.0.1:${PORT}/index.html`,
		reuseExistingServer: false,
		timeout: 120_000
	},
	projects: [
		// The full Chromium build (what participants run), not the headless shell.
		{ name: 'chromium', use: { ...devices['Desktop Chrome'], channel: 'chromium' }, testIgnore: /crash\.spec/ },
		{ name: 'webkit', use: { ...devices['Desktop Safari'] }, testIgnore: /crash\.spec/ },
		// The headless shell runs workers in the page's renderer without OOM protection, so a
		// hook that exhausts memory crashes the tab: the crash-recovery path is tested there.
		{ name: 'chromium-headless-shell', use: { ...devices['Desktop Chrome'] }, testMatch: /crash\.spec/ }
	]
});
