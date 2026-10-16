import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vitest/config';

// Builder component tests in jsdom (Testing Library): files named `*.svelte.test.ts`, which
// the node project in vite.config.ts excludes. Compiled for the browser, not for SSR.
export default defineConfig({
	plugins: [svelte({ configFile: false, compilerOptions: { runes: true } })],
	resolve: { conditions: ['browser'] },
	test: {
		name: 'builder-dom',
		environment: 'jsdom',
		expect: { requireAssertions: true },
		include: ['src/**/*.svelte.test.ts']
	}
});
