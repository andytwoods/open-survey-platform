import { defineConfig, devices } from '@playwright/test';

// Participant app end to end against the real backend: `make runtime-e2e`.
// e2e/server.py starts osp-api on a fresh SQLite store, publishes the test surveys and
// serves the built app. Device profiles per runtime-design §6.
const PORT = Number(process.env.OSP_RUNTIME_E2E_PORT ?? 4391);

export default defineConfig({
	testDir: 'e2e',
	fullyParallel: true,
	workers: process.env.CI ? 2 : 4,
	timeout: 90_000,
	expect: { timeout: 15_000 },
	forbidOnly: !!process.env.CI,
	reporter: process.env.CI ? 'github' : 'list',
	use: {
		baseURL: `http://127.0.0.1:${PORT}`,
		trace: 'retain-on-failure'
	},
	webServer: {
		command: `vite build --logLevel warn && uv run --locked --with uvicorn==0.38.0 python e2e/server.py --port ${PORT}`,
		url: `http://127.0.0.1:${PORT}/__test/surveys`,
		reuseExistingServer: false,
		timeout: 180_000,
		env: { VIRTUAL_ENV: '' }
	},
	projects: [
		{ name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } } },
		{ name: 'pixel-7', use: { ...devices['Pixel 7'] } },
		{ name: 'iphone-se', use: { ...devices['iPhone SE'] } }
	]
});
