import { REGISTRY } from './registry.ts';

/** Every registered op id, sorted. */
export function opIds(): string[] {
	return [...REGISTRY.keys()].sort();
}

/** id, label and area per op, sorted by id (the op catalogue without params schemas). */
export function opCatalogue(): { id: string; label: string; area: string }[] {
	return opIds().map((id) => {
		const s = REGISTRY.get(id)!;
		return { id, label: s.label, area: s.area };
	});
}
