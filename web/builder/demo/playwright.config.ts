import { defineConfig } from '@playwright/test';

// Scripted demo videos (`make demo-videos`, docs/demos.md). Not tests and not part of
// `make check`: each *.demo.ts records one or two raw WebM files into .build/demo/raw/,
// which demo/render.sh turns into MP4 + GIF. Same servers as the builder e2e (a throwaway
// osp-api on a fresh SQLite store that also serves the participant app, and the built
// pages behind `vite preview`), on ports the Makefile picks so parallel runs never collide.
const PORT = Number(process.env.OSP_DEMO_PORT ?? 4517);
const API_PORT = Number(process.env.OSP_DEMO_API_PORT ?? 4518);

export default defineConfig({
	testDir: '.',
	testMatch: '*.demo.ts',
	outputDir: '../../../.build/demo/test-results',
	// One at a time, in file order: the videos are paced for a viewer, not for speed.
	workers: 1,
	fullyParallel: false,
	retries: 0,
	// Generous: on a loaded machine (parallel agents' test runs) a video can take minutes.
	timeout: 600_000,
	expect: { timeout: 20_000 },
	reporter: 'list',
	use: {
		baseURL: `http://127.0.0.1:${PORT}`,
		// The device scale must match SCALE in overlay.ts (1280 x 720 viewport → 1920 x 1080).
		launchOptions: { slowMo: Number(process.env.OSP_DEMO_SLOWMO ?? 25), args: ['--force-device-scale-factor=1.5'] }
	},
	webServer: [
		{
			command: `pnpm -C ../runtime exec vite build --logLevel warn && uv run --locked --with uvicorn python e2e/api_server.py --port ${API_PORT}`,
			cwd: '..',
			url: `http://127.0.0.1:${API_PORT}/api/health`,
			reuseExistingServer: !!process.env.OSP_DEMO_REUSE,
			timeout: 180_000,
			env: { VIRTUAL_ENV: '' }
		},
		{
			command: `vite build --logLevel warn && vite preview --host 127.0.0.1 --port ${PORT} --strictPort`,
			cwd: '..',
			url: `http://127.0.0.1:${PORT}`,
			env: { OSP_API_URL: `http://127.0.0.1:${API_PORT}` },
			reuseExistingServer: !!process.env.OSP_DEMO_REUSE,
			timeout: 180_000
		}
	],
	projects: [{ name: 'chromium', use: { browserName: 'chromium' } }]
});
