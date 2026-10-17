<script lang="ts">
	import { Dialog } from '@osp/ui-components';
	import ConditionBuilder from './ConditionBuilder.svelte';
	import type { ExpressionService } from './service';
	import type { ConditionField, ConditionOp, ExprNode, QuestionInfo } from './types';

	/**
	 * The condition builder in a modal, opened from the property panel's "Edit condition…".
	 * Apply emits the op through `onOps` and closes; Cancel and Escape close without one.
	 */
	let {
		open = $bindable(false),
		title = 'Edit condition',
		description,
		questions,
		value = null,
		target,
		field,
		surveyId = null,
		service,
		heading,
		onOps
	}: {
		open?: boolean;
		title?: string;
		description?: string;
		questions: readonly QuestionInfo[];
		value?: ExprNode | null;
		target: string;
		field?: ConditionField;
		surveyId?: string | null;
		service: ExpressionService;
		/** Passed to the builder; defaults to "Show this question if…". */
		heading?: string;
		onOps: (ops: ConditionOp[]) => void;
	} = $props();

	function apply(ops: ConditionOp[]) {
		onOps(ops);
		open = false;
	}
</script>

<Dialog bind:open {title} {description} size="lg" placement="top">
	{#if open}
		<ConditionBuilder
			{questions}
			{value}
			{target}
			{field}
			{surveyId}
			{service}
			{heading}
			onOps={apply}
			oncancel={() => (open = false)}
		/>
	{/if}
</Dialog>
