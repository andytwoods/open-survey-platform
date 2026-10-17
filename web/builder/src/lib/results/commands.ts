/** Palette commands for the Results page (tasks V2, V6), registered by the shell. */
import type { Command } from '../commands/registry';

export function resultsCommands(a: {
	inResults: () => boolean;
	canOpen: () => boolean;
	open: () => void;
	/** Toggle presentation mode (only the cards; task V6). */
	present?: () => void;
}): Command[] {
	const out: Command[] = [
		{
			id: 'view.results',
			label: 'Open results',
			group: 'View',
			keywords: ['results', 'responses', 'charts', 'statistics', 'counts', 'data', 'analysis'],
			enabled: () => a.canOpen() && !a.inResults(),
			run: a.open
		}
	];
	if (a.present) {
		out.push({
			id: 'view.results.present',
			label: 'Present results (only the cards)',
			group: 'View',
			keywords: ['present', 'presentation', 'fullscreen', 'hide', 'print', 'results', 'charts'],
			enabled: () => a.inResults(),
			run: a.present
		});
	}
	return out;
}
