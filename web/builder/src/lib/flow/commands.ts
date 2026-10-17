/** Palette commands for the flow editor, registered by the shell next to its own. */
import type { Command } from '../commands/registry';

export function flowCommands(a: {
	inFlow: () => boolean;
	canOpen: () => boolean;
	open: () => void;
	addNode: () => void;
}): Command[] {
	return [
		{
			id: 'view.flow',
			label: 'Open survey flow',
			group: 'View',
			keywords: ['flow', 'branch', 'randomiser', 'logic', 'survey flow', 'end'],
			enabled: () => a.canOpen() && !a.inFlow(),
			run: a.open
		},
		{
			id: 'flow.addNode',
			label: 'Add flow node',
			group: 'Flow',
			keywords: ['insert', 'block', 'branch', 'randomiser', 'assign', 'quota', 'end'],
			enabled: a.inFlow,
			run: a.addNode
		}
	];
}
