import { defineConfig } from 'vitest/config';

// Engine tests. Run through `make engine-test`, which first builds the fixture plans and
// parity vectors into .build/ with Python (scripts/build_fixtures.py).
export default defineConfig({
	test: {
		name: 'engine',
		environment: 'node',
		include: ['test/**/*.test.ts'],
		testTimeout: 60_000
	}
});
