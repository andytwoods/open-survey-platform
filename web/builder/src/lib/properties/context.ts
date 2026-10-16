/** Context key for the panel's registry of text buffers (so `flush()` reaches them all). */
export const BUFFERS = Symbol('osp-property-buffers');

export interface Flushable {
	flush(): void;
}

export type BufferRegistry = Set<Flushable>;
