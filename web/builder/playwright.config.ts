import { fileURLToPath } from 'node:url';
import { defineConfig, devices } from '@playwright/test';
import { E2E_OUT_DIR, E2E_PORT } from './e2e/out-dir';

// End-to-end tests for the builder: `make web-e2e` (not part of `make check`). Needs `uv`.
// Override the ports (OSP_E2E_PORT / OSP_E2E_API_PORT) to run beside another checkout's
// servers: an existing server on the port is reused, whatever it was built from.
const PORT = E2E_PORT;
const API_PORT = Number(process.env.OSP_E2E_API_PORT ?? 4318);
const OUT_DIR = fileURLToPath(E2E_OUT_DIR);

export default defineConfig({
	testDir: 'e2e',
	// One snapshot per name and per OS (`-darwin`, `-linux`, `-win32`): text measures and
	// rasterises differently on each, well past the loose tolerance below. Draw a platform's
	// set on that platform (`make web-e2e E2E_ARGS="--update-snapshots all"`); for Linux and
	// Windows the "Draw e2e snapshots" workflow does it on the CI runners (web/builder/README.md).
	snapshotPathTemplate: '{testDir}/__screenshots__/{testFilePath}/{arg}-{platform}{ext}',
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
			command: `vite build --logLevel warn --outDir "${OUT_DIR}" && vite preview --outDir "${OUT_DIR}" --host 127.0.0.1 --port ${PORT} --strictPort`,
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
