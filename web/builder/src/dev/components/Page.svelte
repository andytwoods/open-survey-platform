<script lang="ts">
	import Plus from '@lucide/svelte/icons/plus';
	import Trash from '@lucide/svelte/icons/trash';
	import {
		Announcer,
		Button,
		Dialog,
		IconButton,
		Input,
		Select,
		Tabs,
		Tooltip,
		theme,
		toast
	} from '@osp/ui-components';
	import { onMount } from 'svelte';

	// Developer gallery of @osp/ui-components (axe-checked in e2e/components.spec.ts).
	let name = $state('');
	let colour = $state('');
	let dialogOpen = $state(false);
	onMount(() => theme.init());
</script>


{#snippet one()}<p>First panel content.</p>{/snippet}
{#snippet two()}<p>Second panel content.</p>{/snippet}

<main class="gallery">
	<h1>Component gallery</h1>

	<section aria-labelledby="h-buttons">
		<h2 id="h-buttons">Buttons</h2>
		<div class="row">
			<Button variant="primary">Primary</Button>
			<Button>Secondary</Button>
			<Button variant="ghost">Ghost</Button>
			<Button variant="danger">Delete</Button>
			<Button disabled>Disabled</Button>
			<Button size="sm">Small</Button>
			<IconButton icon={Plus} label="Add item" variant="secondary" />
			<IconButton icon={Trash} label="Remove item" />
			<Tooltip text="Explains the thing">
				{#snippet trigger(props)}
					<button type="button" class="osp-button" {...props}>Hover me</button>
				{/snippet}
			</Tooltip>
		</div>
	</section>

	<section aria-labelledby="h-fields">
		<h2 id="h-fields">Fields</h2>
		<div class="row">
			<Input label="Name" bind:value={name} description="Shown to participants." />
			<Input label="Code" value="Q1 1" error="Codes cannot contain spaces." />
			<Select
				label="Colour"
				bind:value={colour}
				options={[
					{ value: 'red', label: 'Red' },
					{ value: 'green', label: 'Green' },
					{ value: 'blue', label: 'Blue', disabled: true }
				]}
			/>
		</div>
	</section>

	<section aria-labelledby="h-tabs">
		<h2 id="h-tabs">Tabs</h2>
		<Tabs
			label="Example tabs"
			tabs={[
				{ value: 'one', label: 'One', content: one },
				{ value: 'two', label: 'Two', content: two }
			]}
		/>
	</section>

	<section aria-labelledby="h-feedback">
		<h2 id="h-feedback">Dialog and toast</h2>
		<div class="row">
			<Button onclick={() => (dialogOpen = true)}>Open dialog</Button>
			<Button onclick={() => toast('Saved.', { kind: 'success' })}>Show toast</Button>
			<Button onclick={() => theme.toggle()}>Toggle theme</Button>
		</div>
	</section>
</main>

<Dialog bind:open={dialogOpen} title="Example dialog" description="Focus is trapped until you close it.">
	<Input label="Something" />
	{#snippet footer()}
		<Button onclick={() => (dialogOpen = false)}>Cancel</Button>
		<Button variant="primary" onclick={() => (dialogOpen = false)}>Done</Button>
	{/snippet}
</Dialog>

<Announcer />

<style>
	.gallery {
		max-width: 56rem;
		margin: 0 auto;
		padding: var(--space-6) var(--space-4);
	}
	h1 {
		font-size: var(--text-xl);
	}
	h2 {
		font-size: var(--text-lg);
		margin-block: var(--space-6) var(--space-3);
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		gap: var(--space-3);
	}
</style>
