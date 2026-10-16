/**
 * Local buffer for a text field (builder-design §4: no round trip per keystroke).
 * `input()` holds the latest value and restarts a pause timer; the value is committed
 * (one op transaction) after the pause or on `flush()` (blur, selection change, undo).
 */
export interface Timers {
	set: (fn: () => void, ms: number) => unknown;
	clear: (handle: unknown) => void;
}

const realTimers: Timers = {
	set: (fn, ms) => setTimeout(fn, ms),
	clear: (h) => clearTimeout(h as ReturnType<typeof setTimeout>)
};

export class TextBuffer {
	#value: string | null = null;
	#timer: unknown = null;
	readonly #commit: (value: string) => void;
	readonly #delay: number;
	readonly #timers: Timers;
	readonly #onDirty: (dirty: boolean) => void;

	constructor(
		commit: (value: string) => void,
		{
			delay = 800,
			timers = realTimers,
			onDirty = () => {}
		}: { delay?: number; timers?: Timers; onDirty?: (dirty: boolean) => void } = {}
	) {
		this.#commit = commit;
		this.#delay = delay;
		this.#timers = timers;
		this.#onDirty = onDirty;
	}

	get dirty(): boolean {
		return this.#value !== null;
	}

	input(value: string) {
		const wasDirty = this.dirty;
		this.#value = value;
		if (this.#timer !== null) this.#timers.clear(this.#timer);
		this.#timer = this.#timers.set(() => this.flush(), this.#delay);
		if (!wasDirty) this.#onDirty(true);
	}

	/** Commit the buffered value now, if any. */
	flush() {
		if (this.#timer !== null) this.#timers.clear(this.#timer);
		this.#timer = null;
		const value = this.#value;
		if (value === null) return;
		this.#value = null;
		this.#onDirty(false);
		this.#commit(value);
	}

	/** Drop the buffered value without committing. */
	cancel() {
		if (this.#timer !== null) this.#timers.clear(this.#timer);
		this.#timer = null;
		if (this.#value !== null) {
			this.#value = null;
			this.#onDirty(false);
		}
	}
}
