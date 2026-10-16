<script lang="ts">
	/**
	 * Static sample of a participant page covering the main question types, drawn only from
	 * the theme's tokens (themeToCssVars on the frame). Presentation only: no survey logic;
	 * it is replaced by R5's participant widgets once they land.
	 */
	let { header, uid }: { header: string; uid: string } = $props();

	const OPTIONS = ['Not at all', 'A little', 'Quite a lot', 'Very much'];
	const HABITS = ['Coffee', 'Exercise', 'Screens in bed'];
</script>

<header class="survey-header">
	<span class="logo"></span>
	<span>{header}</span>
</header>

<div class="survey-page">
	<div class="progress">
		<p class="page-title">Page 2 of 5</p>
		<div class="bar"><span style:inline-size="40%"></span></div>
	</div>

	<fieldset class="question">
		<legend>How rested do you feel today?</legend>
		<p class="hint">Choose one answer.</p>
		<div class="choices">
			{#each OPTIONS as option, i (option)}
				<label class="choice">
					<input type="radio" name="rested-{uid}" checked={i === 2} />
					<span>{option}</span>
				</label>
			{/each}
		</div>
	</fieldset>

	<fieldset class="question">
		<legend>Which did you have after 6 pm?</legend>
		<p class="hint">Choose all that apply.</p>
		<div class="choices">
			{#each HABITS as habit, i (habit)}
				<label class="choice">
					<input type="checkbox" checked={i !== 1} />
					<span>{habit}</span>
				</label>
			{/each}
		</div>
	</fieldset>

	<fieldset class="question">
		<legend>How well did you sleep?</legend>
		<div class="scale">
			{#each [1, 2, 3, 4, 5] as n (n)}
				<label class="point">
					<input type="radio" name="scale-{uid}" checked={n === 4} />
					<span>{n}</span>
				</label>
			{/each}
		</div>
		<div class="anchors"><span>Very badly</span><span>Very well</span></div>
	</fieldset>

	<div class="question">
		<label class="q-label" for="hours-{uid}">How many hours did you sleep?</label>
		<p class="hint">A whole number, e.g. 7.</p>
		<input id="hours-{uid}" class="text-input" aria-invalid="true" value="seven-ish" />
		<p class="error">Enter a number of hours, like 7.</p>
	</div>

	<div class="question">
		<label class="q-label" for="where-{uid}">Where did you sleep?</label>
		<select id="where-{uid}" class="text-input">
			<option>At home</option>
			<option>Somewhere else</option>
		</select>
	</div>

	<div class="question">
		<label class="q-label" for="notes-{uid}">Anything else about last night?</label>
		<textarea id="notes-{uid}" class="text-input area" rows="3">Woke up once around 3 am.</textarea>
	</div>

	<p class="hint">Questions? Read the <a href="#top">study information</a>.</p>

	<nav class="survey-nav">
		<button type="button" class="nav-button secondary">Back</button>
		<button type="button" class="nav-button primary">Next</button>
	</nav>
</div>

<style>
	.survey-header {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-3) var(--space-4);
		font-weight: var(--weight-bold);
		border-block-end: 1px solid var(--color-border);
		background: var(--color-surface);
	}
	.logo {
		flex: none;
		inline-size: 1.75rem;
		block-size: 1.75rem;
		border-radius: var(--radius-sm);
		background: var(--color-accent);
	}
	.survey-page {
		max-width: 42rem;
		margin-inline: auto;
		padding: var(--space-4);
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}
	@container (min-width: 600px) {
		.survey-page {
			padding: var(--space-6);
		}
	}
	.page-title {
		margin: 0 0 var(--space-1);
		font-size: var(--text-sm);
		color: var(--color-text-muted);
	}
	.bar {
		block-size: 0.375rem;
		border-radius: var(--radius-full);
		background: var(--color-surface-sunken);
		overflow: hidden;
	}
	.bar span {
		display: block;
		block-size: 100%;
		background: var(--color-accent);
	}
	.question {
		margin: 0;
		padding: var(--space-4);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		min-inline-size: 0;
	}
	legend,
	.q-label {
		display: block;
		font-size: var(--text-lg);
		font-weight: var(--weight-medium);
		line-height: var(--leading-tight);
		padding: 0;
		margin-block-end: var(--space-2);
	}
	.hint {
		margin: 0 0 var(--space-3);
		font-size: var(--text-sm);
		color: var(--color-text-muted);
	}
	.hint a {
		color: var(--color-accent);
	}
	.error {
		margin: var(--space-2) 0 0;
		font-size: var(--text-sm);
		color: var(--color-danger);
	}

	/* Choices: list (default) */
	.choices {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	.choice {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		min-block-size: var(--osp-touch-target);
		padding-inline: var(--space-2);
		border-radius: var(--radius-sm);
	}
	.choice input {
		inline-size: 1.25rem;
		block-size: 1.25rem;
		margin: 0;
		accent-color: var(--color-accent);
	}
	:global([data-osp-choice='cards']) .choices {
		gap: var(--space-2);
	}
	:global([data-osp-choice='cards']) .choice {
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
	}
	:global([data-osp-choice='cards']) .choice:has(input:checked) {
		background: var(--color-selected);
		border-color: var(--color-accent);
		box-shadow: inset 0 0 0 1px var(--color-accent);
	}
	:global([data-osp-choice='buttons']) .choices {
		flex-flow: row wrap;
		gap: var(--space-2);
	}
	:global([data-osp-choice='buttons']) .choice {
		justify-content: center;
		padding: 0 var(--space-4);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		font-weight: var(--weight-medium);
	}
	:global([data-osp-choice='buttons']) .choice input {
		position: absolute;
		opacity: 0;
		inline-size: 1px;
		block-size: 1px;
	}
	:global([data-osp-choice='buttons']) .choice:has(input:checked) {
		background: var(--color-accent);
		border-color: var(--color-accent);
		color: var(--color-on-accent);
	}

	/* Rating scale */
	.scale {
		display: grid;
		grid-template-columns: repeat(5, 1fr);
		gap: var(--space-2);
	}
	.point {
		position: relative;
		display: flex;
		align-items: center;
		justify-content: center;
		min-block-size: var(--osp-touch-target);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		font-weight: var(--weight-medium);
	}
	.point input {
		position: absolute;
		opacity: 0;
	}
	.point:has(input:checked) {
		background: var(--color-accent);
		border-color: var(--color-accent);
		color: var(--color-on-accent);
	}
	.anchors {
		display: flex;
		justify-content: space-between;
		margin-block-start: var(--space-1);
		font-size: var(--text-sm);
		color: var(--color-text-muted);
	}

	.text-input {
		display: block;
		inline-size: 100%;
		max-inline-size: 20rem;
		min-block-size: var(--control-height);
		padding: 0 var(--space-3);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		/* Never below 16 px, whatever the theme says (runtime-design §6). */
		font-size: var(--osp-input-font-size);
	}
	.text-input.area {
		max-inline-size: none;
		padding-block: var(--space-2);
		resize: none;
	}
	.text-input[aria-invalid='true'] {
		border-color: var(--color-danger);
		border-width: 2px;
	}

	.survey-nav {
		display: flex;
		justify-content: space-between;
		gap: var(--space-3);
		padding-block-start: var(--space-2);
	}
	.nav-button {
		min-block-size: var(--control-height);
		min-inline-size: 6rem;
		padding: 0 var(--space-5);
		border-radius: var(--radius-md);
		font: inherit;
		font-weight: var(--weight-medium);
	}
	.nav-button.secondary {
		background: var(--color-surface-raised);
		color: var(--color-text);
		border: 1px solid var(--color-border-strong);
	}
	.nav-button.primary {
		background: var(--color-accent);
		color: var(--color-on-accent);
		border: 2px solid var(--color-accent);
	}
	:global([data-osp-button='outline']) .nav-button.primary {
		background: transparent;
		color: var(--color-accent);
	}
</style>
