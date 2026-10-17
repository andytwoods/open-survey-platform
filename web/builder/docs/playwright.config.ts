import { defineConfig } from '@playwright/test';

// Screenshots for the docs site (`make docs-screenshots`, docs/ at the repo root). Not tests
// and not part of `make check`: screenshots.ts drives the real builder and participant app
// against a throwaway stack (the e2e api_server on a fresh SQLite store, which also serves
// the participant app, and the built pages behind `vite preview`), with the invented demo
// survey from ../demo/seed.ts, and writes PNGs into docs/assets/screenshots/. Ports come
// from the Makefile so parallel runs never collide (an empty variable, e.g. when the
// Makefile's free-port helper finds no python3, falls back to the defaults).
const PORT = Number(process.env.OSP_DOCS_PORT || 4617);
const API_PORT = Number(process.env.OSP_DOCS_API_PORT || 4618);

export default defineConfig({
	testDir: '.',
	testMatch: 'screenshots.ts',
	outputDir: '../../../.build/docs-screenshots/test-results',
	workers: 1,
	fullyParallel: false,
	retries: 0,
	timeout: 300_000,
	expect: { timeout: 20_000 },
	reporter: 'list',
	use: {
		baseURL: `http://127.0.0.1:${PORT}`,
		colorScheme: 'light',
		viewport: { width: 1280, height: 800 }
	},
	webServer: [
		{
			command: `pnpm -C ../runtime exec vite build --logLevel warn && uv run --locked --with uvicorn python e2e/api_server.py --port ${API_PORT}`,
			cwd: '..',
			url: `http://127.0.0.1:${API_PORT}/api/health`,
			reuseExistingServer: !!process.env.OSP_DOCS_REUSE,
			timeout: 180_000,
			env: { VIRTUAL_ENV: '' }
		},
		{
			command: `vite build --logLevel warn && vite preview --host 127.0.0.1 --port ${PORT} --strictPort`,
			cwd: '..',
			url: `http://127.0.0.1:${PORT}`,
			env: { OSP_API_URL: `http://127.0.0.1:${API_PORT}` },
			reuseExistingServer: !!process.env.OSP_DOCS_REUSE,
			timeout: 180_000
		}
	],
	projects: [{ name: 'chromium', use: { browserName: 'chromium' } }]
});
