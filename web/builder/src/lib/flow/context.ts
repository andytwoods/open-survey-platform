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
	dragStart(id: string): void;
	dragEnd(): void;
	drop(gap: ListRef & { index: number }): void;
	openCondition(id: string): void;
}

const KEY = Symbol('osp-flow');

export const setFlowCtx = (c: FlowCtx) => setContext(KEY, c);
export const flowCtx = () => getContext<FlowCtx>(KEY);
