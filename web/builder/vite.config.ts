import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vitest/config';
import { DEV_PAGES, PAGES } from './dev-host/pages.ts';
import { ospPages } from './dev-host/plugin.ts';

// The builder: a Vite multi-page build (planning/pages-split.md F1, D1). One JS entry per
// page (src/pages/*.ts), shared chunks, and build/manifest.json (page → js + css) for a
// host to write its tags. `base: './'` keeps the output relocatable under any static URL.
// The dev-only gallery pages (src/pages/dev/*) are built only with OSP_DEV_PAGES=1
// (`make web-e2e`), never by `make web-build`.
const devPages = process.env.OSP_DEV_PAGES === '1';
const entries: Record<string, string> = devPages ? { ...PAGES, ...DEV_PAGES } : { ...PAGES };

// API calls go to `osp-api` on the same origin (the dev config's apiBase is /api), so in
// dev and preview /api is proxied to it and the browser needs no CORS. The default is
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

export default defineConfig(({ command }) => ({
	base: command === 'build' ? './' : '/',
	appType: 'custom',
	publicDir: 'static',
	server: { proxy },
	preview: { proxy },
	plugins: [
		svelte({
			configFile: false,
			compilerOptions: {
				// Runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) => (filename.split(/[/\\]/).includes('node_modules') ? undefined : true)
			}
		}),
		ospPages({ entries: command === 'build' ? entries : { ...PAGES, ...DEV_PAGES }, devPages })
	],
	build: {
		outDir: 'build',
		emptyOutDir: true,
		target: 'es2022',
		manifest: true,
		rollupOptions: {
			input: entries,
			// Keep each entry's `mount` export.
			preserveEntrySignatures: 'exports-only',
			output: {
				entryFileNames: 'assets/[name]-[hash].js',
				chunkFileNames: 'assets/[name]-[hash].js',
				assetFileNames: 'assets/[name]-[hash][extname]'
			}
		}
	},
	test: {
		name: 'builder',
		environment: 'node',
		expect: { requireAssertions: true },
		include: ['src/**/*.{test,spec}.{js,ts}', 'dev-host/**/*.test.ts'],
		exclude: ['src/**/*.svelte.{test,spec}.{js,ts}']
	}
}));
