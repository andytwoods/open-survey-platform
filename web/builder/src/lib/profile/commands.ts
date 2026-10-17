/** Palette command for the lab's panel profile page (task B21), registered by the shell. */
import type { Command } from '../commands/registry';

export function profileCommands(a: { inProfile: () => boolean; canOpen: () => boolean; open: () => void }): Command[] {
	return [
		{
			id: 'view.profile',
			label: 'Open lab panel profile',
			group: 'View',
			keywords: ['profile', 'properties', 'panel', 'custom properties', 'lab', 'hide', 'defaults'],
			enabled: () => a.canOpen() && !a.inProfile(),
			run: a.open
		}
	];
}
