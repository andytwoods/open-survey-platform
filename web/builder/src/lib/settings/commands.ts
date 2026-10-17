/** Palette commands for Survey settings and Publish (task B12), registered by the shell. */
import type { Command } from '../commands/registry';

export function settingsCommands(a: {
	inSettings: () => boolean;
	canOpen: () => boolean;
	open: () => void;
	publish: () => void;
}): Command[] {
	return [
		{
			id: 'view.settings',
			label: 'Open survey settings',
			group: 'View',
			keywords: ['settings', 'save mode', 'retention', 'languages', 'consent', 'back', 'resume'],
			enabled: () => a.canOpen() && !a.inSettings(),
			run: a.open
		},
		{
			id: 'survey.publish',
			label: 'Publish survey',
			group: 'Survey',
			keywords: ['publish', 'go live', 'participant link', 'release', 'version'],
			enabled: a.canOpen,
			run: a.publish
		}
	];
}
