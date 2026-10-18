import { defineConfig } from 'vitest/config';

// Validator parity tests. Run through `make spec-test`, which first writes Python's
// diagnostics for every vector document into .build/ (scripts/build_vectors.py).
export default defineConfig({
	test: {
		name: 'spec',
		environment: 'node',
		include: ['test/**/*.test.ts'],
		testTimeout: 120_000
	}
});
