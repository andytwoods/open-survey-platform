import { defineConfig, devices } from '@playwright/test';

// End-to-end tests for the builder: `make web-e2e` (not part of `make check`). Needs `uv`.
// Override the ports (OSP_E2E_PORT / OSP_E2E_API_PORT) to run beside another checkout's
// servers: an existing server on the port is reused, whatever it was built from.
const PORT = Number(process.env.OSP_E2E_PORT ?? 4317);
const API_PORT = Number(process.env.OSP_E2E_API_PORT ?? 4318);

export default defineConfig({
	testDir: 'e2e',
	// One snapshot per name, not per OS: snapshots are reviewed by eye, compared loosely.
	snapshotPathTemplate: '{testDir}/__screenshots__/{testFilePath}/{arg}{ext}',
	fullyParallel: true,
	forbidOnly: !!process.env.CI,
	reporter: process.env.CI ? 'github' : 'list',
	use: {
		baseURL: `http://127.0.0.1:${PORT}`,
		trace: 'retain-on-failure'
	},
	expect: {
		toHaveScreenshot: { maxDiffPixelRatio: 0.02, animations: 'disabled', caret: 'hide' }
	},
	webServer: [
		{
			// Throwaway osp-api on SQLite (e2e/api_server.py) for the end-to-end editing tests.
			// The participant app is built first so a published link can be opened (B12).
			command: `pnpm -C ../runtime exec vite build --logLevel warn && uv run --locked --with uvicorn python e2e/api_server.py --port ${API_PORT}`,
			url: `http://127.0.0.1:${API_PORT}/api/health`,
			reuseExistingServer: !process.env.CI,
			timeout: 120_000
		},
		{
			// The production pages plus the dev-only galleries (OSP_DEV_PAGES=1), served by the
			// reference host in dev-host/ at today's URLs with the dev config.
			command: `vite build --logLevel warn && vite preview --host 127.0.0.1 --port ${PORT} --strictPort`,
			url: `http://127.0.0.1:${PORT}`,
			env: { OSP_API_URL: `http://127.0.0.1:${API_PORT}`, OSP_DEV_PAGES: '1' },
			reuseExistingServer: !process.env.CI,
			timeout: 120_000
		}
	],
	projects: [
		{
			name: 'chromium',
			use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } }
		}
	]
});
