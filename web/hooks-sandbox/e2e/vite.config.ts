import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';
import { FRAME_SCRIPT, frameDocument } from '../src/frame-script.ts';

const FRAME_SCRIPT_HASH = `'sha256-${createHash('sha256').update(FRAME_SCRIPT).digest('base64')}'`;

// Builds the e2e harness (index.html embeds runtime.html) into e2e/build.
const root = fileURLToPath(new URL('./harness', import.meta.url));

export default defineConfig({
	root,
	logLevel: 'warn',
	plugins: [
		{
			name: 'frame-script-hash',
			transformIndexHtml: { order: 'pre', handler: (html) => html.replaceAll('%FRAME_SCRIPT_HASH%', FRAME_SCRIPT_HASH) },
			// The sandbox document as a static file, for a separate sandbox origin (frameUrl).
			generateBundle() {
				this.emitFile({ type: 'asset', fileName: 'sandbox-frame.html', source: frameDocument(FRAME_SCRIPT_HASH) });
			}
		}
	],
	build: {
		outDir: fileURLToPath(new URL('./build', import.meta.url)),
		emptyOutDir: true,
		modulePreload: false,
		minify: false,
		rollupOptions: {
			input: { index: `${root}/index.html`, runtime: `${root}/runtime.html` }
		}
	}
});
