import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vitest/config';

// Component behaviour tests (Testing Library in jsdom). Layout, axe and screen widths are
// covered by Playwright in web/builder/e2e (widgets.spec.ts).
export default defineConfig({
	plugins: [svelte({ configFile: false, compilerOptions: { runes: true } })],
	resolve: { conditions: ['browser'] },
	test: {
		name: 'ui-components',
		environment: 'jsdom',
		expect: { requireAssertions: true },
		include: ['src/**/*.test.ts'],
		setupFiles: ['./src/survey/test-setup.ts']
	}
});
