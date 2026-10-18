import { defineConfig } from 'vitest/config';

// Ops tests. Run through `make ops-parity`, which first writes the Python parity vectors
// into .build/ (python/osp-ops/scripts/ops_vectors.py).
export default defineConfig({
	test: {
		name: 'ops',
		environment: 'node',
		include: ['test/**/*.test.ts'],
		testTimeout: 120_000
	}
});
