import { defineConfig } from 'vitest/config';

// One `vitest run` for the whole web workspace.
export default defineConfig({
	test: {
		projects: [
			'./builder/vite.config.ts',
			'./ui-components/vitest.config.ts',
			{
				test: {
					name: 'api-client',
					environment: 'node',
					include: ['api-client/src/**/*.test.ts']
				}
			},
			{
				test: {
					name: 'tooling',
					environment: 'node',
					include: ['tooling/**/*.test.ts'],
					testTimeout: 60_000
				}
			}
		]
	}
});
