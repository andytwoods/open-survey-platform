import { defineConfig } from 'vitest/config';

// `vite build` bundles the CLI (with @osp/engine and big.js) into dist/cli.js, which the
// server runs as a Node sidecar (osp_runtime.sim_sidecar), and the dev-only fake-participant
// driver into dist/fake.js (`osp-cli fake-responses`, task DS1).
// Tests: `make sim-test` (builds the fixture plans first, like engine-test).
export default defineConfig({
	build: {
		ssr: true,
		outDir: 'dist',
		target: 'node24',
		emptyOutDir: true,
		minify: false,
		rollupOptions: {
			input: { cli: 'src/cli.ts', fake: 'src/fake-cli.ts' },
			output: { entryFileNames: '[name].js', chunkFileNames: '[name]-[hash].js', format: 'es' }
		}
	},
	ssr: { noExternal: true, target: 'node' },
	test: {
		name: 'engine-sim',
		environment: 'node',
		include: ['test/**/*.test.ts'],
		testTimeout: 120_000
	}
});
