// Display-only icon per mock node type / card family.
import type { LucideIcon } from '@lucide/svelte';
import TextCursorInput from '@lucide/svelte/icons/text-cursor-input';
import FileText from '@lucide/svelte/icons/file-text';
import Grid3x3 from '@lucide/svelte/icons/grid-3x3';
import Hash from '@lucide/svelte/icons/hash';
import Info from '@lucide/svelte/icons/info';
import Layers from '@lucide/svelte/icons/layers';
import ListChecks from '@lucide/svelte/icons/list-checks';
import SlidersHorizontal from '@lucide/svelte/icons/sliders-horizontal';
import type { MockNode } from '../mock/survey';

const FAMILY: Record<NonNullable<MockNode['family']>, LucideIcon> = {
	choice: ListChecks,
	text: TextCursorInput,
	number: Hash,
	matrix: Grid3x3,
	scale: SlidersHorizontal,
	note: Info
};

export function iconFor(node: MockNode): LucideIcon {
	if (node.type === 'page') return FileText;
	if (node.type === 'block') return Layers;
	return (node.family && FAMILY[node.family]) || Info;
}
