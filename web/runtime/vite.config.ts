import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vitest/config';

// The participant app: one static bundle. The server serves `dist/index.html` for every
// `/s/{slug}` URL and the hashed files under `/r/` (immutable). Not SvelteKit.
export default defineConfig({
	base: '/r/',
	plugins: [svelte({ configFile: false, compilerOptions: { runes: true } })],
	resolve: { conditions: ['browser'] },
	build: {
		outDir: 'dist',
		assetsDir: '.',
		target: 'es2022',
		cssCodeSplit: false,
		modulePreload: false
	},
	server: {
		proxy: { '/api': 'http://127.0.0.1:8000' }
	},
	test: {
		name: 'runtime',
		environment: 'node',
		include: ['test/**/*.test.ts']
	}
});
