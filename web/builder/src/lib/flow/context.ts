/** What the flow view shares with its (recursive) node lists. */
import { getContext, setContext } from 'svelte';
import type { SurveyStore } from '../sync/survey-store.svelte';
import type { FlowDiagnostic, ListRef } from './model';

export interface FlowCtx {
	readonly store: SurveyStore;
	readonly survey: unknown;
	readonly language: string;
	readonly diagnostics: Map<string, FlowDiagnostic[]>;
	/** Id of the node being dragged, if any. */
	readonly dragging: string | null;
	isCollapsed(id: string): boolean;
	toggle(id: string): void;
	openAdd(at: ListRef & { index: number }): void;
	remove(id: string): void;
	moveBy(id: string, dir: -1 | 1): void;
	/** Key (`data-gap`) of the gap under the pointer while dragging. */
	readonly overGap: string | null;
	dragStart(id: string): void;
	dragOver(gap: string | null): void;
	/** Cancel a drag. */
	dragEnd(): void;
	/** Drop the dragged node on the gap under the pointer, if any. */
	drop(): void;
	openCondition(id: string): void;
	/** Open the ending of an outcome in Survey settings → Endings (EN1). */
	openEnding(outcome: string): void;
}

const KEY = Symbol('osp-flow');

export const setFlowCtx = (c: FlowCtx) => setContext(KEY, c);
export const flowCtx = () => getContext<FlowCtx>(KEY);
