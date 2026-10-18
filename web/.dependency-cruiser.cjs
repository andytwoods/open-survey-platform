/**
 * Web workspace boundaries (AGENTS.md §2). Paths are relative to web/.
 *
 *   builder        may import api-client and ui-components
 *   ui-components  must not import api-client (or builder)
 *   api-client     imports neither ui-components nor builder
 *   nothing        imports builder
 *   nothing        reaches outside web/ (python/, spikes/, ...)
 *
 * tooling/boundaries.test.ts proves each rule fails on a deliberate violation.
 */
/** @type {import('dependency-cruiser').IConfiguration} */
module.exports = {
	forbidden: [
		{
			name: 'nothing-imports-builder',
			severity: 'error',
			comment: 'builder is the top of the web stack; nothing may depend on it.',
			from: { pathNot: '^builder/' },
			to: { path: '^builder/' }
		},
		{
			name: 'ui-components-not-to-api-client',
			severity: 'error',
			comment: 'Components are presentational. Data comes in via props from builder.',
			from: { path: '^ui-components/' },
			to: { path: '^api-client/' }
		},
		{
			name: 'api-client-is-a-leaf',
			severity: 'error',
			comment: 'The generated client depends on no other workspace package.',
			from: { path: '^api-client/' },
			to: { path: '^(ui-components|builder)/' }
		},
		{
			name: 'stay-inside-web',
			severity: 'error',
			comment: 'Web code never imports python/, spikes/ or other repo folders directly.',
			from: {},
			to: { path: '^\\.\\./' }
		},
		{
			name: 'not-to-unresolvable',
			severity: 'error',
			comment: 'An import the cruiser cannot resolve could hide a boundary violation.',
			from: {},
			// builder's own #lib package import (package.json "imports").
			to: { couldNotResolve: true, pathNot: '^#lib(/|$)' }
		},
		{
			name: 'no-circular',
			severity: 'error',
			from: {},
			to: { circular: true }
		},
		{
			name: 'tiptap-stays-in-richtext',
			severity: 'error',
			comment:
				'The rich-text editor (Tiptap/ProseMirror, planning/rich-text.md §2) is a builder-only lazy chunk: only builder/src/lib/richtext/ may import it, so the participant runtime and ui-components never carry it.',
			from: { pathNot: '^builder/src/lib/richtext/' },
			to: { path: 'node_modules/(@tiptap/|prosemirror-)' }
		}
	],
	options: {
		doNotFollow: { path: 'node_modules' },
		exclude: { path: '(^|/)(build|dist)/' },
		// Follow workspace symlinks to their real path so rules see e.g. api-client/src/index.ts.
		preserveSymlinks: false,
		tsPreCompilationDeps: true,
		tsConfig: { fileName: require('node:path').join(__dirname, 'tsconfig.depcruise.json') },
		enhancedResolveOptions: {
			exportsFields: ['exports'],
			conditionNames: ['types', 'svelte', 'import', 'default'],
			mainFields: ['svelte', 'module', 'main', 'types'],
			extensions: ['.ts', '.js', '.svelte', '.d.ts']
		}
	}
};
