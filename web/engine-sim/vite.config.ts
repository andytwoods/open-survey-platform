import { defineConfig } from 'vitest/config';

// `vite build` bundles the CLI (with @osp/engine and big.js) into one self-contained file,
// dist/cli.js, which the server runs as a Node sidecar (osp_runtime.sim_sidecar).
// Tests: `make sim-test` (builds the fixture plans first, like engine-test).
export default defineConfig({
	build: {
		ssr: 'src/cli.ts',
		outDir: 'dist',
		target: 'node24',
		emptyOutDir: true,
		minify: false,
		rollupOptions: { output: { entryFileNames: 'cli.js', format: 'es' } }
	},
	ssr: { noExternal: true, target: 'node' },
	test: {
		name: 'engine-sim',
		environment: 'node',
		include: ['test/**/*.test.ts'],
		testTimeout: 120_000
	}
});
