import { defineConfig } from 'vitest/config';
import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';

// Builder API calls go to `osp-api` on the same origin (cookie auth + CSRF origin check).
// In dev and preview, proxy /api to it; `make web-e2e` starts a throwaway one on 4318.
const apiTarget = process.env.OSP_API_URL ?? 'http://127.0.0.1:4318';
const proxy = { '/api': { target: apiTarget, changeOrigin: false } };

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
