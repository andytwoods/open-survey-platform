import { readFileSync } from 'node:fs';
import { defineConfig } from 'vite';

// `make engine-bundle`: the whole engine (with big.js) as one self-contained ES module,
// dist/engine.js. The reproducibility package (osp_targets.repro, task M3) ships it with
// replay.mjs, so a reviewer can replay event logs under plain Node without this repository.
// Not minified, so it can be read; the banner names the exact engine version.
const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')) as {
	version: string;
};

export default defineConfig({
	build: {
		lib: { entry: 'src/index.ts', formats: ['es'], fileName: () => 'engine.js' },
		outDir: 'dist',
		target: 'es2022',
		emptyOutDir: true,
		minify: false,
		rollupOptions: {
			output: {
				banner: `/*! @osp/engine ${pkg.version} (MIT, Open Survey Platform); bundles big.js (MIT) */`
			}
		}
	}
});
