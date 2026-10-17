import { defineConfig } from 'vitest/config';
import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';

// Builder API calls go to `osp-api` on the same origin (cookie auth + CSRF origin check),
// so in dev and preview /api is proxied to it and the browser needs no CORS. The default is
// `make dev`'s `osp-api serve` on 8000; `make web-e2e` points OSP_API_URL at its own on 4318.
// changeOrigin stays false: the API's origin check compares Origin with the Host it sees.
const apiTarget = process.env.OSP_API_URL ?? 'http://127.0.0.1:8000';
// The participant app (`/s/{slug}` and its files under `/r/`) is served by the API host too,
// so a published survey's link opens from the builder's origin (B12; `make web-e2e`).
const proxy = {
	'/api': { target: apiTarget, changeOrigin: false },
	'^/s/': { target: apiTarget, changeOrigin: false },
	'^/r/': { target: apiTarget, changeOrigin: false }
};

export default defineConfig({
	server: { proxy },
	preview: { proxy },
	plugins: [
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},
			// Single-page app: the backend serves build/index.html for every builder route.
			adapter: adapter({ fallback: 'index.html', strict: true })
		})
	],
	test: {
		name: 'builder',
		environment: 'node',
		expect: { requireAssertions: true },
		include: ['src/**/*.{test,spec}.{js,ts}'],
		exclude: ['src/**/*.svelte.{test,spec}.{js,ts}']
	}
});
