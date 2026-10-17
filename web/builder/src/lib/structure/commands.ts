/** Palette commands for pages and blocks (task B20), registered by the shell. */
import type { Command } from '../commands/registry';

export interface StructureCommandActions {
	/** A survey is open in the editor (adds, and the selection's actions). */
	canEdit: () => boolean;
	/** "Add block" also works in the Flow view. */
	canAddBlock: () => boolean;
	/** A block, page or question is selected in the editor. */
	hasTarget: () => boolean;
	addPage: () => void;
	addBlock: () => void;
	rename: () => void;
	duplicate: () => void;
	remove: () => void;
}

export function structureCommands(a: StructureCommandActions): Command[] {
	const onTarget = () => a.canEdit() && a.hasTarget();
	return [
		{
			id: 'structure.addPage',
			label: 'Add page',
			group: 'Survey',
			keywords: ['new', 'insert', 'page', 'screen'],
			enabled: a.canEdit,
			run: a.addPage
		},
		{
			id: 'structure.addBlock',
			label: 'Add block',
			group: 'Survey',
			keywords: ['new', 'insert', 'block', 'section'],
			enabled: a.canAddBlock,
			run: a.addBlock
		},
		{
			id: 'structure.rename',
			label: 'Rename…',
			group: 'Edit',
			keywords: ['title', 'name', 'page', 'block', 'question'],
			enabled: onTarget,
			run: a.rename
		},
		{
			id: 'structure.duplicate',
			label: 'Duplicate',
			group: 'Edit',
			keywords: ['copy', 'clone', 'page', 'block', 'question'],
			enabled: onTarget,
			run: a.duplicate
		},
		{
			id: 'structure.delete',
			label: 'Delete…',
			group: 'Edit',
			keywords: ['remove', 'page', 'block', 'question'],
			enabled: onTarget,
			run: a.remove
		}
	];
}
