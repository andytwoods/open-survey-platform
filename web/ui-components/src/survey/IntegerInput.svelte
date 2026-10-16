<script lang="ts">
	import NumberField from './NumberField.svelte';
	import type { IntegerInputProps } from './types';

	/** Whole number. Value is a canonical string ("-12") or null. */
	let props: IntegerInputProps = $props();
</script>

<NumberField {...props} mode="integer" />
