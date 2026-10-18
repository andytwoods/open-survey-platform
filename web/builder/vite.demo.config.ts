import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig, type Plugin } from 'vite';

// The serverless Pages demo (task DEMO2): the builder pages plus "Take the study", as plain
// static files that run with no server (src/lib/demo/). Built by `make docs-demo` into
// build-demo/, which the docs workflow copies to the site's /demo/. `base: './'` keeps
// every URL relative, so it works under any path (/open-survey-platform/demo/ on Pages).
// The data file (public/data/demo-data.json) is generated first by scripts/demo_data.py.
const root = fileURLToPath(new URL('./demo-site/', import.meta.url));
const staticDir = fileURLToPath(new URL('./static/', import.meta.url));

const PAGES = ['', 'list', 'flow', 'settings', 'appearance', 'themes', 'preview-frame', 'take'];
const input = Object.fromEntries(PAGES.map((p) => [p || 'index', `${root}${p ? `${p}/` : ''}index.html`]));

/** The builder's icons (static/) at the demo's root, as the pages link them. */
function icons(): Plugin {
	return {
		name: 'osp-demo-icons',
		apply: 'build',
		generateBundle() {
			for (const f of readdirSync(staticDir)) {
				if (f === 'robots.txt' || f === 'site.webmanifest') continue;
				this.emitFile({ type: 'asset', fileName: f, source: readFileSync(staticDir + f) });
			}
		}
	};
}

export default defineConfig({
	root,
	base: './',
	appType: 'mpa',
	publicDir: 'public',
	// The runtime's hooks sandbox frame: srcdoc on this origin (web/runtime/vite.config.ts).
	define: { __OSP_HOOKS_FRAME_URL__: JSON.stringify('') },
	plugins: [
		svelte({
			configFile: false,
			compilerOptions: {
				runes: ({ filename }) => (filename.split(/[/\\]/).includes('node_modules') ? undefined : true)
			}
		}),
		icons()
	],
	build: {
		outDir: fileURLToPath(new URL('./build-demo/', import.meta.url)),
		emptyOutDir: true,
		target: 'es2022',
		rollupOptions: { input },
		chunkSizeWarningLimit: 4096
	}
});
