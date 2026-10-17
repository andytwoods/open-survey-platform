/**
 * Commands for the Appearance view, registered by the shell next to its own. They only
 * switch views; editing the theme happens in the view, and undo/redo reuse edit.undo /
 * edit.redo (the shell routes them to the theme editor while this view is open).
 */
import type { Command } from '../commands/registry';

export type BuilderView = 'editor' | 'appearance' | 'flow' | 'settings' | 'results' | 'profile';

export function appearanceCommands(a: {
	view: () => BuilderView;
	open: (v: BuilderView) => void;
}): Command[] {
	return [
		{
			id: 'view.appearance',
			label: 'Open Appearance',
			group: 'View',
			keywords: ['theme editor', 'colours', 'colors', 'fonts', 'branding', 'logo', 'style'],
			enabled: () => a.view() !== 'appearance',
			run: () => a.open('appearance')
		},
		{
			id: 'view.editor',
			label: 'Back to survey editor',
			group: 'View',
			keywords: ['outline', 'canvas', 'questions'],
			enabled: () => a.view() !== 'editor',
			run: () => a.open('editor')
		}
	];
}
