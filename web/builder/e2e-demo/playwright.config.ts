import { defineConfig, devices } from '@playwright/test';

// The serverless Pages demo end to end (task DEMO2, `make demo-e2e`): the static build in
// build-demo/ (`make docs-demo` builds it) served by a plain static file server at the
// Pages path, with every /api request aborted by the tests, so a pass proves the demo
// needs no server. Not part of `make check`; CI runs it in the docs workflow.
const PORT = Number(process.env.OSP_PAGES_DEMO_PORT ?? 6437);

export default defineConfig({
	testDir: '.',
	fullyParallel: true,
	forbidOnly: !!process.env.CI,
	reporter: process.env.CI ? 'github' : 'list',
	use: {
		baseURL: `http://127.0.0.1:${PORT}`,
		trace: 'retain-on-failure'
	},
	webServer: {
		command: `node serve.mjs ${PORT}`,
		url: `http://127.0.0.1:${PORT}/open-survey-platform/demo/`,
		reuseExistingServer: !process.env.CI,
		timeout: 30_000
	},
	projects: [
		{
			name: 'chromium',
			use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } }
		}
	]
});
