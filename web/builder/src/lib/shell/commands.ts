/**
 * The shell's commands, as data. Undo/redo go to the survey store (the API's undo/redo)
 * in the editor, to the theme editor in Appearance, and say so in the `?mock` shell.
 */
import type { Command } from '../commands/registry';

export interface ShellActions {
	togglePalette: () => void;
	undo: () => void;
	redo: () => void;
	cyclePane: (dir: 1 | -1) => void;
	toggleTheme: () => void;
	systemTheme: () => void;
	toggleOutline: () => void;
	toggleProperties: () => void;
	outlineCollapsible: () => boolean;
	propertiesCollapsible: () => boolean;
	preview: () => void;
	clearSelection: () => void;
	/** Add a question (the `add_question` op) to the selected or last page. */
	addQuestion: () => void;
	/** True when a real survey is open in the editor view. */
	canEdit: () => boolean;
}

export function shellCommands(a: ShellActions): Command[] {
	return [
		{
			id: 'palette.open',
			label: 'Open command palette',
			group: 'General',
			shortcut: 'Mod+K',
			allowInEditable: true,
			allowInModal: true,
			inPalette: false,
			run: a.togglePalette
		},
		{
			id: 'edit.undo',
			label: 'Undo',
			group: 'Edit',
			shortcut: 'Mod+Z',
			run: a.undo
		},
		{
			id: 'edit.redo',
			label: 'Redo',
			group: 'Edit',
			shortcut: ['Mod+Shift+Z', 'Mod+Y'],
			run: a.redo
		},
		{
			id: 'survey.addQuestion',
			label: 'Add question',
			group: 'Survey',
			keywords: ['new', 'insert', 'item'],
			enabled: a.canEdit,
			run: a.addQuestion
		},
		{
			id: 'selection.clear',
			label: 'Clear selection',
			group: 'Edit',
			keywords: ['deselect'],
			run: a.clearSelection
		},
		{
			id: 'view.nextPane',
			label: 'Focus next pane',
			group: 'View',
			shortcut: 'F6',
			allowInEditable: true,
			run: () => a.cyclePane(1)
		},
		{
			id: 'view.prevPane',
			label: 'Focus previous pane',
			group: 'View',
			shortcut: 'Shift+F6',
			allowInEditable: true,
			run: () => a.cyclePane(-1)
		},
		{
			id: 'view.toggleTheme',
			label: 'Toggle light/dark theme',
			group: 'View',
			keywords: ['dark mode', 'appearance'],
			run: a.toggleTheme
		},
		{
			id: 'view.systemTheme',
			label: 'Use system theme',
			group: 'View',
			keywords: ['appearance', 'auto'],
			run: a.systemTheme
		},
		{
			id: 'view.toggleOutline',
			label: 'Show or hide outline pane',
			group: 'View',
			enabled: a.outlineCollapsible,
			run: a.toggleOutline
		},
		{
			id: 'view.toggleProperties',
			label: 'Show or hide properties pane',
			group: 'View',
			enabled: a.propertiesCollapsible,
			run: a.toggleProperties
		},
		{
			id: 'survey.preview',
			label: 'Preview survey',
			group: 'Survey',
			run: a.preview
		}
	];
}
