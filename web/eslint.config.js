import js from '@eslint/js';
import svelte from 'eslint-plugin-svelte';
import { defineConfig } from 'eslint/config';
import globals from 'globals';
import ts from 'typescript-eslint';

export default defineConfig(
	{
		ignores: [
			'**/node_modules/**',
			'**/build/**',
			'**/dist/**',
			// Generated from /contract/openapi.json by `make contract`.
			'api-client/src/schema.d.ts'
		]
	},
	js.configs.recommended,
	ts.configs.recommended,
	svelte.configs.recommended,
	{
		languageOptions: { globals: { ...globals.browser, ...globals.node } },
		rules: {
			// typescript-eslint recommends turning no-undef off for TypeScript projects.
			'no-undef': 'off',
			// SvelteKit-only rule: the builder pages navigate with full loads from the host's
			// link templates (builder/src/lib/host/links.ts), not SvelteKit's resolve().
			'svelte/no-navigation-without-resolve': 'off',
			// Researcher text is a closed tree rendered as text nodes and our own elements
			// (planning/rich-text.md §7, §10); nothing in web/ may inject HTML.
			'svelte/no-at-html-tags': 'error'
		}
	},
	{
		// CommonJS config files (e.g. .dependency-cruiser.cjs) legitimately use require().
		files: ['**/*.cjs'],
		languageOptions: { sourceType: 'commonjs' },
		rules: { '@typescript-eslint/no-require-imports': 'off' }
	},
	{
		files: ['**/*.svelte', '**/*.svelte.ts', '**/*.svelte.js'],
		languageOptions: {
			parserOptions: {
				projectService: true,
				extraFileExtensions: ['.svelte'],
				parser: ts.parser
			}
		}
	}
);
