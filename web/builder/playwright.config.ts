import { defineConfig, devices } from '@playwright/test';

// End-to-end tests for the builder: `make web-e2e` (not part of `make check`). Needs `uv`.
const PORT = 4317;
const API_PORT = 4318;

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
			command: `uv run --locked --with uvicorn python e2e/api_server.py --port ${API_PORT}`,
			url: `http://127.0.0.1:${API_PORT}/api/health`,
			reuseExistingServer: !process.env.CI,
			timeout: 120_000
		},
		{
			command: `vite build --logLevel warn && vite preview --host 127.0.0.1 --port ${PORT} --strictPort`,
			url: `http://127.0.0.1:${PORT}`,
			env: { OSP_API_URL: `http://127.0.0.1:${API_PORT}` },
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
