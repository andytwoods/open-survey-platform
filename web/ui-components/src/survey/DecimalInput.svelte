<script lang="ts">
	import NumberField from './NumberField.svelte';
	import type { DecimalInputProps } from './types';

	/**
	 * Decimal number, typed with the participant's separator ("3,5" in German). Value is an
	 * exact canonical string with "." ("3.50") or null; it is never converted to a float.
	 */
	let props: DecimalInputProps = $props();
</script>

<NumberField {...props} mode="decimal" />
