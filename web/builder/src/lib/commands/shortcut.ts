/**
 * Keyboard shortcuts as data: "Mod+Shift+Z", "F6", "Mod+K".
 * `Mod` is Cmd on Apple platforms and Ctrl elsewhere. Matching ignores letter case.
 */
export interface ParsedShortcut {
	mod: boolean;
	ctrl: boolean;
	meta: boolean;
	shift: boolean;
	alt: boolean;
	key: string; // lower-case KeyboardEvent.key
}

export interface KeyLike {
	key: string;
	ctrlKey: boolean;
	metaKey: boolean;
	shiftKey: boolean;
	altKey: boolean;
}

const MODIFIERS = new Set(['mod', 'ctrl', 'meta', 'shift', 'alt']);

export function parseShortcut(shortcut: string): ParsedShortcut {
	const parts = shortcut.split('+').map((p) => p.trim());
	const key = parts.pop();
	if (!key) throw new Error(`Empty shortcut: "${shortcut}"`);
	const mods = new Set(parts.map((p) => p.toLowerCase()));
	for (const m of mods) {
		if (!MODIFIERS.has(m)) throw new Error(`Unknown modifier "${m}" in "${shortcut}"`);
	}
	return {
		mod: mods.has('mod'),
		ctrl: mods.has('ctrl'),
		meta: mods.has('meta'),
		shift: mods.has('shift'),
		alt: mods.has('alt'),
		key: key.toLowerCase()
	};
}

export function matchesShortcut(shortcut: string, e: KeyLike, isMac: boolean): boolean {
	const s = parseShortcut(shortcut);
	const wantCtrl = s.ctrl || (s.mod && !isMac);
	const wantMeta = s.meta || (s.mod && isMac);
	return (
		e.key.toLowerCase() === s.key &&
		e.ctrlKey === wantCtrl &&
		e.metaKey === wantMeta &&
		e.shiftKey === s.shift &&
		e.altKey === s.alt
	);
}

/** Human-readable label, e.g. "Ctrl+Shift+Z" or "⌘⇧Z". */
export function formatShortcut(shortcut: string, isMac: boolean): string {
	const s = parseShortcut(shortcut);
	const key = s.key.length === 1 ? s.key.toUpperCase() : s.key.replace(/^f(\d+)$/, 'F$1');
	if (isMac) {
		return [
			s.ctrl ? '⌃' : '',
			s.alt ? '⌥' : '',
			s.shift ? '⇧' : '',
			s.mod || s.meta ? '⌘' : '',
			key
		].join('');
	}
	return [s.mod || s.ctrl ? 'Ctrl' : '', s.meta ? 'Meta' : '', s.alt ? 'Alt' : '', s.shift ? 'Shift' : '', key]
		.filter(Boolean)
		.join('+');
}

/** Value for aria-keyshortcuts ("Control+Z" / "Meta+Z"). */
export function ariaShortcut(shortcut: string, isMac: boolean): string {
	const s = parseShortcut(shortcut);
	const key = s.key.length === 1 ? s.key.toUpperCase() : s.key.replace(/^f(\d+)$/, 'F$1');
	return [
		s.ctrl || (s.mod && !isMac) ? 'Control' : '',
		s.meta || (s.mod && isMac) ? 'Meta' : '',
		s.alt ? 'Alt' : '',
		s.shift ? 'Shift' : '',
		key
	]
		.filter(Boolean)
		.join('+');
}

export function detectMac(): boolean {
	const nav = globalThis.navigator as (Navigator & { userAgentData?: { platform?: string } }) | undefined;
	// navigator.platform first: it is what the OS keyboard layer (and Playwright) agree on.
	const platform = nav?.platform || nav?.userAgentData?.platform || '';
	return /mac|iphone|ipad|ipod/i.test(platform);
}
