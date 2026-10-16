/**
 * Command registry: every user action in the shell is a command, described as data
 * (id, label, shortcut, handler), the UI-side mirror of the backend op registry.
 * Buttons, the command palette and keyboard shortcuts all dispatch through `run(id)`,
 * so there is one place that decides whether an action is enabled.
 */
import { matchesShortcut, type KeyLike } from './shortcut';

export interface Command {
	/** Stable dotted id, e.g. "edit.undo". */
	id: string;
	label: string;
	/** Palette group heading. */
	group?: string;
	/** One shortcut, or several (the first is the one displayed). */
	shortcut?: string | readonly string[];
	/** Extra words the palette matches on. */
	keywords?: readonly string[];
	/** Disabled commands are hidden from shortcuts and shown greyed in the palette. */
	enabled?: () => boolean;
	/** Run even when focus is in a text field (default false, so native undo etc. work). */
	allowInEditable?: boolean;
	/** Shortcut still works while a modal is open (default false). */
	allowInModal?: boolean;
	/** List in the palette (default true). */
	inPalette?: boolean;
	run: () => void;
}

export interface KeyEventLike extends KeyLike {
	target?: EventTarget | null;
	defaultPrevented?: boolean;
	preventDefault?: () => void;
}

export function shortcutsOf(cmd: Command): readonly string[] {
	if (!cmd.shortcut) return [];
	return typeof cmd.shortcut === 'string' ? [cmd.shortcut] : cmd.shortcut;
}

function isEditable(target: EventTarget | null | undefined): boolean {
	const el = target as (HTMLElement & { isContentEditable?: boolean }) | null | undefined;
	if (!el || typeof el.tagName !== 'string') return false;
	const tag = el.tagName.toLowerCase();
	return tag === 'input' || tag === 'textarea' || tag === 'select' || el.isContentEditable === true;
}

export class CommandRegistry {
	#commands = new Map<string, Command>();
	#listeners = new Set<() => void>();
	readonly isMac: boolean;
	readonly #isModalOpen: () => boolean;

	/**
	 * `isModalOpen`: while it returns true, shortcuts only reach commands marked
	 * `allowInModal` (the modal owns the keyboard). Running by id is unaffected.
	 */
	constructor({ isMac = false, isModalOpen = () => false }: { isMac?: boolean; isModalOpen?: () => boolean } = {}) {
		this.isMac = isMac;
		this.#isModalOpen = isModalOpen;
	}

	/** Register a command. Returns an unregister function. Duplicate ids throw. */
	register(cmd: Command): () => void {
		if (!cmd.id) throw new Error('Command needs an id');
		if (this.#commands.has(cmd.id)) throw new Error(`Command "${cmd.id}" is already registered`);
		this.#commands.set(cmd.id, cmd);
		this.#emit();
		return () => {
			if (this.#commands.get(cmd.id) === cmd) {
				this.#commands.delete(cmd.id);
				this.#emit();
			}
		};
	}

	registerAll(cmds: readonly Command[]): () => void {
		const offs = cmds.map((c) => this.register(c));
		return () => offs.forEach((off) => off());
	}

	get(id: string): Command | undefined {
		return this.#commands.get(id);
	}

	/** All commands in registration order. */
	list(): Command[] {
		return [...this.#commands.values()];
	}

	isEnabled(id: string): boolean {
		const cmd = this.#commands.get(id);
		if (!cmd) return false;
		try {
			return cmd.enabled ? cmd.enabled() : true;
		} catch {
			return false;
		}
	}

	/** Run a command by id. Returns false (and does nothing) if it is unknown or disabled. */
	run(id: string): boolean {
		const cmd = this.#commands.get(id);
		if (!cmd || !this.isEnabled(id)) return false;
		cmd.run();
		return true;
	}

	/** The enabled command whose shortcut matches this key event, if any. */
	match(e: KeyEventLike): Command | undefined {
		const editable = isEditable(e.target);
		const modal = this.#isModalOpen();
		for (const cmd of this.#commands.values()) {
			if (editable && !cmd.allowInEditable) continue;
			if (modal && !cmd.allowInModal) continue;
			if (!shortcutsOf(cmd).some((s) => matchesShortcut(s, e, this.isMac))) continue;
			if (this.isEnabled(cmd.id)) return cmd;
		}
		return undefined;
	}

	/** Keydown handler: runs the matching command and prevents the browser default. */
	handleKeydown(e: KeyEventLike): boolean {
		if (e.defaultPrevented) return false;
		const cmd = this.match(e);
		if (!cmd) return false;
		e.preventDefault?.();
		cmd.run();
		return true;
	}

	/** Called whenever a command is added or removed. Returns an unsubscribe function. */
	subscribe(fn: () => void): () => void {
		this.#listeners.add(fn);
		return () => this.#listeners.delete(fn);
	}

	#emit() {
		for (const fn of this.#listeners) fn();
	}
}
