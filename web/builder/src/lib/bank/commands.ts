/** Palette commands for the question bank (task QB5), registered by the shell. */
import type { Command } from '../commands/registry';

export function bankCommands(a: {
	inBank: () => boolean;
	canOpen: () => boolean;
	open: () => void;
	/** A block, page or question is selected in the editor and a survey is open. */
	canSave: () => boolean;
	saveToBank: () => void;
	canShowBank: () => boolean;
	showBank: () => void;
}): Command[] {
	return [
		{
			id: 'view.bank',
			label: 'Open question bank page',
			group: 'View',
			keywords: ['bank', 'library', 'instruments', 'questionnaire', 'scale', 'licensed'],
			enabled: () => a.canOpen() && !a.inBank(),
			run: a.open
		},
		{
			id: 'bank.save',
			label: 'Save to bank…',
			group: 'Edit',
			keywords: ['bank', 'library', 'reuse', 'save question', 'save page', 'save block'],
			enabled: a.canSave,
			run: a.saveToBank
		},
		{
			id: 'bank.show',
			label: 'Show the bank',
			group: 'View',
			keywords: ['bank', 'insert instrument', 'phq', 'gad', 'search bank'],
			enabled: a.canShowBank,
			run: a.showBank
		}
	];
}
