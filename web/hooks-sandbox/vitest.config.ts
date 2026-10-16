import { defineConfig } from 'vitest/config';

// Unit tests (node): manifest, validation, engine integration with a fake invoker.
// The sandbox itself is tested in real browsers by `make hooks-e2e` (Playwright).
export default defineConfig({
	test: {
		name: 'hooks-sandbox',
		environment: 'node',
		include: ['test/**/*.test.ts']
	}
});
