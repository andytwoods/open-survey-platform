import { defineConfig } from 'vitest/config';

// Unit tests for the comparator and the fixture selection (no browser, no server).
export default defineConfig({
	test: { name: 'harness', environment: 'node', include: ['test/**/*.test.ts'] }
});
