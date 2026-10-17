import { createHash } from 'node:crypto';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig, type Plugin } from 'vitest/config';
import { FRAME_SCRIPT, frameDocument } from '../hooks-sandbox/src/frame-script.ts';

// The participant app: one static bundle. The server serves `dist/index.html` for every
// `/s/{slug}` URL and the hashed files under `/r/` (immutable). Not SvelteKit.

/** The hooks sandbox frame's only script, by hash (runtime-design §7a). */
const FRAME_SCRIPT_HASH = `'sha256-${createHash('sha256').update(FRAME_SCRIPT).digest('base64')}'`;

/**
 * Production: serve the hooks sandbox from a separate site (see src/lib/hooks.ts), e.g.
 * `OSP_HOOKS_FRAME_URL=https://sandbox.example.org/hooks-frame.html vite build`, and deploy
 * `dist/hooks-frame.html` there. Empty: a `srcdoc` iframe on this origin.
 */
const FRAME_URL = process.env.OSP_HOOKS_FRAME_URL ?? '';
const frameOrigin = (() => {
	try {
		return FRAME_URL ? new URL(FRAME_URL).origin : '';
	} catch {
		throw new Error(`OSP_HOOKS_FRAME_URL is not a URL: ${FRAME_URL}`);
	}
})();

/**
 * The page CSP (runtime-design §7: no inline scripts, no third-party origins). A `srcdoc`
 * iframe inherits it, so it also allows the hooks frame script (by hash) and the blob:
 * worker that frame starts; the frame's own CSP narrows that to `default-src 'none'`.
 * Inline `style` attributes are allowed (Svelte and the theme set them; no script).
 */
export const CSP = [
	"default-src 'self'",
	`script-src 'self' ${FRAME_SCRIPT_HASH}`,
	"worker-src blob:",
	"style-src 'self' 'unsafe-inline'",
	"img-src 'self' data: blob:",
	"font-src 'self'",
	"connect-src 'self'",
	`frame-src 'self'${frameOrigin ? ` ${frameOrigin}` : ''}`,
	"object-src 'none'",
	"base-uri 'none'",
	"form-action 'none'"
].join('; ');

function securityPolicy(): Plugin {
	return {
		name: 'osp-runtime-csp',
		apply: 'build', // the dev server injects inline styles and a websocket
		transformIndexHtml: {
			order: 'post',
			handler: (html) =>
				html.replace('<head>', `<head>\n\t\t<meta http-equiv="Content-Security-Policy" content="${CSP}" />`)
		},
		// The sandbox document, for a separate sandbox origin (HookHost `frameUrl`).
		generateBundle() {
			this.emitFile({ type: 'asset', fileName: 'hooks-frame.html', source: frameDocument(FRAME_SCRIPT_HASH) });
		}
	};
}

export default defineConfig({
	base: '/r/',
	plugins: [svelte({ configFile: false, compilerOptions: { runes: true } }), securityPolicy()],
	define: { __OSP_HOOKS_FRAME_URL__: JSON.stringify(FRAME_URL) },
	resolve: { conditions: ['browser'] },
	build: {
		outDir: 'dist',
		assetsDir: '.',
		target: 'es2022',
		cssCodeSplit: false,
		modulePreload: false
	},
	server: {
		// `make dev`'s osp-api; OSP_API_URL overrides it (as in web/builder).
		proxy: { '/api': process.env.OSP_API_URL ?? 'http://127.0.0.1:8000' }
	},
	test: {
		name: 'runtime',
		environment: 'node',
		include: ['test/**/*.test.ts']
	}
});
