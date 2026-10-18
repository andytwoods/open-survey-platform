<script lang="ts">
	import { untrack } from 'svelte';
	import { isLevel, pipeCandidates, pipeProblems, RichTextEditor, type RichValue } from '../richtext';
	import BufferedInput from './BufferedInput.svelte';
	import {
		editorButtonLabel,
		enumOptions,
		externalSummary,
		fallbackText,
		isMissingTranslation,
		localised,
		parseNumber,
		richIn,
		setPropertyOp,
		textIn,
		textValue,
		type OpAddress
	} from './logic';
	import type { OpenEditorRequest, PanelDiagnostic, PanelOp, PropertySpec } from './types';

	/**
	 * One property: label, the field editor picked by `spec.kind`, help, translation hint
	 * and inline diagnostics (all wired through `aria-describedby`). No per-type code.
	 * Participant-facing text (`richtext`, or `text` with a `rich` level) gets the rich
	 * editor at the level the schema declares (planning/rich-text.md §9).
	 */
	let {
		id,
		propertyKey,
		spec,
		raw,
		address,
		language,
		defaultLanguage,
		survey,
		diagnostics = [],
		pointer = '',
		onOp,
		onOpenEditor,
		onDirty
	}: {
		id: string;
		propertyKey: string;
		spec: PropertySpec;
		/** The target's own value (undefined when unset). */
		raw: unknown;
		address: OpAddress | null;
		language: string;
		defaultLanguage: string;
		survey: unknown;
		diagnostics?: PanelDiagnostic[];
		/** RFC 6901 pointer of this property in the survey document (for chip diagnostics). */
		pointer?: string;
		onOp: (op: PanelOp) => void;
		onOpenEditor?: (request: OpenEditorRequest) => void;
		onDirty?: (dirty: boolean) => void;
	} = $props();

	// The parent re-creates fields when the target or language changes, so the address
	// is fixed for this instance: a buffer flushed while the selection moves on still
	// edits the object it was typed into.
	const addr = untrack(() => address);
	/** Latest own value, kept as a plain variable so a flush on teardown sees this target's. */
	let lastRaw = untrack(() => raw);
	$effect.pre(() => {
		lastRaw = raw;
	});

	const kind = $derived(spec.kind);
	/** The rich editor's level: the schema's `rich`, else stem for `richtext`; plain `text` has none. */
	const level = $derived(isLevel(spec.rich) ? spec.rich : kind === 'richtext' ? 'stem' : null);
	const label = $derived(localised(spec.label, language) || propertyKey);
	const help = $derived(localised(spec.help, language));
	const shown = $derived(raw === undefined ? spec.default : raw);
	const readonly = $derived(addr === null);
	const translatable = $derived(!!spec.translatable && (kind === 'text' || kind === 'richtext'));
	const missing = $derived(translatable && isMissingTranslation(raw, language));
	const hasError = $derived(diagnostics.some((d) => d.severity === 'error'));
	let numberError = $state('');

	const labelId = $derived(`${id}-label`);
	const helpId = $derived(`${id}-help`);
	const langId = $derived(`${id}-lang`);
	const pipeId = $derived(`${id}-pipe`);
	const diagId = $derived(`${id}-diag`);
	const numErrId = $derived(`${id}-numerr`);
	const describedBy = $derived(
		[
			translatable && langId,
			help && helpId,
			level !== null && pipeId,
			numberError && numErrId,
			diagnostics.length > 0 && diagId
		]
			.filter(Boolean)
			.join(' ') || undefined
	);

	// Pipe chips (planning/rich-text.md §4): candidates from the survey the client holds
	// (items before this one), and the server's diagnostics on the chips they are about.
	const pipes = $derived(level === null ? null : pipeCandidates(survey, { before: addr?.target, lang: language }));
	const problems = $derived(level === null ? new Map<string, string>() : pipeProblems(raw, language, diagnostics, pointer));
	// Editing a translation: the default-language value is the reference (planning/rich-text.md §5).
	const reference = $derived(
		translatable && language !== defaultLanguage ? { value: richIn(raw, defaultLanguage), language: defaultLanguage } : null
	);

	function emit(value: unknown) {
		if (addr) onOp(setPropertyOp(addr, value));
	}

	function commitText(text: RichValue) {
		emit(textValue(spec, lastRaw, language, defaultLanguage, text));
	}

	function commitNumber(text: string) {
		const n = parseNumber(text);
		if (n === null) {
			numberError = 'Enter a number.';
			return;
		}
		numberError = '';
		emit(n);
	}

	const options = $derived(kind === 'enum' ? enumOptions(spec, survey, language) : []);
	const enumValue = $derived(typeof shown === 'string' ? shown : '');
	const allowEmpty = $derived(!spec.required && spec.default === undefined);

	const checked = $derived(shown === true);
</script>

<div
	class="prop"
	data-property={propertyKey}
	data-kind={kind}
	data-invalid={hasError || undefined}
	data-missing-translation={missing || undefined}
>
	<div class="prop-head">
		<label id={labelId} for={id}>
			{label}{#if spec.required}<span class="req" aria-hidden="true"> *</span>{/if}
		</label>
		{#if translatable}
			<span class="lang" id={langId}>
				<span class="osp-visually-hidden">Language:</span>
				<span class="lang-code">{language}</span>{#if missing}<span class="missing">
						Missing translation</span
					>{/if}
			</span>
		{/if}
	</div>

	{#if level !== null}
		<RichTextEditor
			{id}
			value={richIn(shown, language)}
			{level}
			{pipes}
			{problems}
			placeholder={missing ? fallbackText(raw, defaultLanguage) : ''}
			{reference}
			labelledBy={labelId}
			{describedBy}
			required={spec.required}
			invalid={hasError}
			{readonly}
			lang={translatable ? language : undefined}
			onCommit={commitText}
			{onDirty}
		/>
	{:else if kind === 'text'}
		<BufferedInput
			{id}
			value={textIn(shown, language)}
			placeholder={missing ? fallbackText(raw, defaultLanguage) : ''}
			{describedBy}
			required={spec.required}
			invalid={hasError}
			{readonly}
			onCommit={commitText}
			{onDirty}
		/>
	{:else if kind === 'number'}
		<BufferedInput
			{id}
			value={typeof shown === 'number' ? String(shown) : ''}
			inputmode="decimal"
			{describedBy}
			required={spec.required}
			invalid={hasError || !!numberError}
			{readonly}
			onCommit={commitNumber}
			{onDirty}
		/>
	{:else if kind === 'bool'}
		<button
			{id}
			type="button"
			role="switch"
			class="switch"
			aria-checked={checked}
			aria-labelledby={labelId}
			aria-describedby={describedBy}
			disabled={readonly}
			onclick={() => emit(!checked)}
		>
			<span class="track" aria-hidden="true"><span class="thumb"></span></span>
			<span class="state" aria-hidden="true">{checked ? 'On' : 'Off'}</span>
		</button>
	{:else if kind === 'enum'}
		<select
			{id}
			class="osp-prop-select"
			value={enumValue}
			aria-describedby={describedBy}
			aria-required={spec.required || undefined}
			aria-invalid={hasError || undefined}
			disabled={readonly}
			onchange={(e) => {
				const v = e.currentTarget.value;
				emit(v === '' ? undefined : v);
			}}
		>
			{#if allowEmpty || enumValue === ''}
				<option value="">Not set</option>
			{/if}
			{#each options as o (o.value)}
				<option value={o.value}>{o.label}</option>
			{/each}
			{#if enumValue !== '' && !options.some((o) => o.value === enumValue)}
				<option value={enumValue}>{enumValue} (not available)</option>
			{/if}
		</select>
	{:else}
		<!-- choicelist, rows, condition, expression: summarised here, edited in their own editor. -->
		<div class="external">
			<span class="summary" data-testid="summary">{externalSummary(kind, shown)}</span>
			<button
				{id}
				type="button"
				class="open-editor"
				aria-labelledby="{labelId} {id}"
				aria-describedby={describedBy}
				aria-haspopup="dialog"
				disabled={!onOpenEditor || readonly}
				onclick={() =>
					addr &&
					onOpenEditor?.({
						kind,
						path: propertyKey,
						target: addr.target,
						property: addr.property,
						value: raw
					})}>{editorButtonLabel(kind)}</button
			>
		</div>
	{/if}

	{#if help}<p class="help" id={helpId}>{help}</p>{/if}
	{#if level !== null}
		<p class="help pipe" id={pipeId}>
			Use <em>Insert answer</em> in the toolbar, or type <code>{'${'}</code>, to pipe in an earlier answer.
		</p>
	{/if}
	{#if numberError}<p class="diag" data-severity="error" id={numErrId}>{numberError}</p>{/if}
	{#if diagnostics.length}
		<ul class="diags" id={diagId}>
			{#each diagnostics as d, i (i)}
				<li class="diag" data-severity={d.severity} data-code={d.code}>
					<span class="osp-visually-hidden">{d.severity}:</span>
					{d.message}
				</li>
			{/each}
		</ul>
	{/if}
</div>

<style>
	.prop {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	.prop-head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--space-2);
	}
	label {
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
	}
	.req {
		color: var(--color-danger);
	}
	.lang {
		display: inline-flex;
		gap: var(--space-2);
		align-items: baseline;
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
	.lang-code {
		padding: 0 var(--space-1);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		text-transform: uppercase;
		font-family: var(--font-mono);
	}
	.missing {
		color: var(--color-text);
		font-weight: var(--weight-medium);
	}
	.help {
		margin: 0;
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
	.pipe code {
		font-family: var(--font-mono);
		padding: 0 0.2rem;
		border-radius: var(--radius-sm);
		background: var(--color-surface-sunken);
		color: var(--color-text);
	}
	.diags {
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.diag {
		margin: 0;
		font-size: var(--text-xs);
		color: var(--color-text);
		padding-left: var(--space-2);
		border-left: 3px solid var(--color-warning);
	}
	.diag[data-severity='error'] {
		border-left-color: var(--color-danger);
	}
	.diag[data-severity='info'] {
		border-left-color: var(--color-border-strong);
	}
	.switch {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		align-self: flex-start;
		padding: var(--space-1) 0;
		border: 0;
		background: none;
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-sm);
		cursor: pointer;
	}
	.track {
		position: relative;
		width: 2.25rem;
		height: 1.25rem;
		border-radius: var(--radius-full);
		background: var(--color-surface-sunken);
		border: 1px solid var(--color-border-strong);
		transition: background 120ms;
	}
	.thumb {
		position: absolute;
		top: 1px;
		left: 1px;
		width: calc(1.25rem - 4px);
		height: calc(1.25rem - 4px);
		border-radius: var(--radius-full);
		background: var(--color-text-muted);
		transition: transform 120ms;
	}
	.switch[aria-checked='true'] .track {
		background: var(--color-accent);
		border-color: var(--color-accent);
	}
	.switch[aria-checked='true'] .thumb {
		background: var(--color-on-accent);
		transform: translateX(1rem);
	}
	.switch:focus-visible,
	.open-editor:focus-visible,
	.osp-prop-select:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 2px;
	}
	.switch:disabled {
		cursor: not-allowed;
		opacity: 0.6;
	}
	.osp-prop-select {
		height: var(--control-height);
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-sm);
	}
	.osp-prop-select[aria-invalid='true'] {
		border-color: var(--color-danger);
	}
	.external {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
		min-width: 0;
	}
	.summary {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: var(--text-sm);
		color: var(--color-text-muted);
	}
	.open-editor {
		flex: none;
		height: var(--control-height);
		padding: 0 var(--space-3);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-sm);
		cursor: pointer;
	}
	.open-editor:hover:not(:disabled) {
		background: var(--color-surface-sunken);
	}
	.open-editor:disabled {
		cursor: not-allowed;
		opacity: 0.6;
	}
</style>
