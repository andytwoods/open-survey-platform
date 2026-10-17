/** Palette command for the Results page (task V2), registered by the shell. */
import type { Command } from '../commands/registry';

export function resultsCommands(a: { inResults: () => boolean; canOpen: () => boolean; open: () => void }): Command[] {
	return [
		{
			id: 'view.results',
			label: 'Open results',
			group: 'View',
			keywords: ['results', 'responses', 'charts', 'statistics', 'counts', 'data', 'analysis'],
			enabled: () => a.canOpen() && !a.inResults(),
			run: a.open
		}
	];
}
