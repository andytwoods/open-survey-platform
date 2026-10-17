/**
 * The shell's commands, as data. Undo/redo go to the survey store (the API's undo/redo)
 * in the editor, to the theme editor in Appearance, and say so in the `?mock` shell.
 */
import type { Command } from '../commands/registry';
import { QUESTION_TYPES, type QuestionTypeId } from '../question-types/catalogue';

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
	/** Open the type picker to add a question to the selected or last page. */
	addQuestion: () => void;
	/** Add a question of this type (the `add_question` op) straight away. */
	addQuestionOfType: (type: QuestionTypeId) => void;
	/** Open the type picker for the selected question. */
	changeQuestionType: () => void;
	/** True when a question is selected in the editor. */
	canChangeType: () => boolean;
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
			label: 'Add question…',
			group: 'Survey',
			keywords: ['new', 'insert', 'item', 'type'],
			enabled: a.canEdit,
			run: a.addQuestion
		},
		...QUESTION_TYPES.map(
			(t): Command => ({
				id: `survey.addQuestion.${t.id}`,
				label: addTypeLabel(t.id, t.name),
				group: 'Survey',
				keywords: ['new', 'insert', ...t.keywords],
				enabled: a.canEdit,
				run: () => a.addQuestionOfType(t.id)
			})
		),
		{
			id: 'question.changeType',
			label: 'Change question type…',
			group: 'Edit',
			keywords: ['convert', 'switch', 'turn into', 'type'],
			enabled: a.canChangeType,
			run: a.changeQuestionType
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

/** "Add single choice question"; a note is not a question, so "Add note". */
export function addTypeLabel(id: QuestionTypeId, name: string): string {
	return id === 'note' ? 'Add note' : `Add ${name.toLowerCase()} question`;
}
