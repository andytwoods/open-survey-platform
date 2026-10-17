<script lang="ts">
	import { announce, Announcer, Button, Dialog, PaneResizer, Tabs, theme, toast } from '@osp/ui-components';
	import { api } from '../api';
	import DiagnosticsStrip from '../diagnostics/DiagnosticsStrip.svelte';
	import { ExportCheckState, type CheckResult } from '../diagnostics/export-check.svelte';
	import { propertyFocus } from '../diagnostics/focus.svelte';
	import { exportBadges, ownerOf, SURVEY_ID, type ExportBadge, type Owner } from '../diagnostics/model';
	import { JsonDraft } from '../json/json-draft.svelte';
	import JsonView from '../json/JsonView.svelte';
	import AppearanceView from '../appearance/AppearanceView.svelte';
	import { appearanceCommands, type BuilderView } from '../appearance/commands';
	import { themeEditor } from '../appearance/theme-editor.svelte';
	import { flowCommands } from '../flow/commands';
	import { requestAddBlock, requestAddNode } from '../flow/flow-ui.svelte';
	import FlowView from '../flow/FlowView.svelte';
	import PublishDialog from '../publish/PublishDialog.svelte';
	import type { PublishProblem } from '../publish/model';
	import { settingsCommands } from '../settings/commands';
	import SettingsView from '../settings/SettingsView.svelte';
	import { onDestroy, onMount, tick, untrack } from 'svelte';
	import { CommandRegistry } from '../commands/registry';
	import { detectMac } from '../commands/shortcut';
	import { health } from '../health.svelte';
	import { leaveTo, link, optionalLink } from '../host/links';
	import { resultsCommands } from '../results/commands';
	import { MOCK_SURVEY } from '../mock/survey';
	import { addedQuestionId, allIds, defaultLanguage, outlineFromSurvey, surveyTitle, targetPage } from '../model/outline';
	import { StructureActions } from '../structure/actions.svelte';
	import AddPageButton from '../structure/AddPageButton.svelte';
	import { structureCommands } from '../structure/commands';
	import OutlineActions from '../structure/OutlineActions.svelte';
	import StructureDeleteDialog from '../structure/StructureDeleteDialog.svelte';
	import StructureMenu, { type MenuTarget } from '../structure/StructureMenu.svelte';
	import { selection } from '../selection.svelte';
	import MoveToDialog from '../outline/MoveToDialog.svelte';
	import { OutlineMover } from '../outline/mover.svelte';
	import type { DropTarget } from '../outline/moves';
	import { outlineSelection } from '../outline/multi-select.svelte';
	import { findNode } from '../outline/tree-nav';
	import type { SurveyStore } from '../sync/survey-store.svelte';
	import ConflictBanner from './ConflictBanner.svelte';
	import CanvasPane from './CanvasPane.svelte';
	import CommandPalette from './CommandPalette.svelte';
	import { shellCommands } from './commands';
	import OutlineTree from './OutlineTree.svelte';
	import { cyclePane } from './panes';
	import PropertiesPane from './PropertiesPane.svelte';
	import PreviewPanel from '../preview/PreviewPanel.svelte';
	import { propertySchemas } from '../properties/schemas.svelte';
	import {
		isQuestionType,
		lastUsedType,
		questionTypeInfo,
		rememberType,
		type QuestionTypeId
	} from '../question-types/catalogue';
	import InsertAtDialog from '../question-types/InsertAtDialog.svelte';
	import { TypeDrag } from '../question-types/type-drag.svelte';
	import TypeChangeDialog, { type TypeChangeRequest } from '../question-types/TypeChangeDialog.svelte';
	import TypePickerDialog from '../question-types/TypePickerDialog.svelte';
	import TypeToolbox from '../question-types/TypeToolbox.svelte';
	import TopBar from './TopBar.svelte';

	/**
	 * Which view fills the area under the top bar (each has its own route), and the survey
	 * being edited. Without a store the shell shows the static mock tree (`?mock`).
	 */
	let { view = 'editor', store = null }: { view?: BuilderView; store?: SurveyStore | null } = $props();
	const editing = $derived(view === 'editor');

	// Below these widths a pane collapses and opens as an overlay from the top bar.
	const PROPERTIES_BREAKPOINT = 1024;
	const OUTLINE_BREAKPOINT = 720;

	const registry = new CommandRegistry({
		isMac: detectMac(),
		isModalOpen: () =>
			paletteOpen ||
			(previewOpen && !store) ||
			moveToOpen ||
			pickerOpen ||
			insertAtOpen ||
			!!typeChange ||
			!!menuTarget ||
			!!structure.deleteRequest
	});
	const mockPages = MOCK_SURVEY.children ?? [];
	// Outline moves show at once (optimistic) and are reconciled with the server's reply.
	const mover = new OutlineMover();
	const serverPages = $derived(store ? outlineFromSurvey(store.survey) : mockPages);
	const pages = $derived(mover.view(serverPages));

	function moveItems(ids: string[], target: DropTarget) {
		if (!store) return;
		const s = store;
		return mover.move((ops) => s.submit(ops), pages, ids, target);
	}

	let moveToOpen = $state(false);
	const canMoveSelection = () => {
		const t = selection.id ? findNode(pages, selection.id)?.type : undefined;
		return editing && !!store && (t === 'question' || t === 'page' || t === 'block');
	};
	const title = $derived(store ? surveyTitle(store.survey) || store.title : MOCK_SURVEY.label);

	// Selection survives patches; it is cleared only when its object is gone (deleted, undone).
	$effect(() => {
		if (store && selection.id && selection.id !== SURVEY_ID && !allIds(pages).has(selection.id)) selection.clear();
	});

	// A rejected edit (422): say so, visibly and to screen readers.
	$effect(() => {
		const r = store?.rejection;
		if (!r) return;
		const n = r.diagnostics.length;
		// untrack: toast() reads and writes the toast list, which must not re-run this effect.
		untrack(() =>
			toast(n ? `${r.message} ${n === 1 ? r.diagnostics[0].message : `${n} problems.`}` : r.message, {
				kind: 'error'
			})
		);
	});

	// JSON view (B9) and diagnostics strip + export badges (B10).
	let canvasTab = $state('canvas');
	let diagnosticsOpen = $state(false);
	const jsonDraft = $derived(store ? new JsonDraft(store) : null);
	const exportCheck = new ExportCheckState(async (surveyId, target) => {
		try {
			const { data, error } = await api.GET('/api/surveys/{survey_id}/export-check', {
				params: { path: { survey_id: surveyId }, query: { target } }
			});
			if (data) return { ok: true, data: data as CheckResult };
			const m = (error as { message?: unknown } | undefined)?.message;
			return { ok: false, message: typeof m === 'string' ? m : 'Request failed.' };
		} catch (e) {
			return { ok: false, message: (e as Error)?.message || 'Network error' };
		}
	});
	onDestroy(() => exportCheck.dispose());
	const badges = $derived(
		store ? exportBadges(store.survey, exportCheck.diagnostics, exportCheck.target) : new Map<string, ExportBadge[]>()
	);

	/** Go to what a diagnostic or badge is about: its property if it has one, else its card. */
	async function goTo(owner: Owner) {
		canvasTab = 'canvas';
		if (propertiesCollapsible) {
			propertiesOpen = true;
			outlineOpen = false;
		}
		selection.select(owner.id);
		if (owner.properties.length || owner.id === SURVEY_ID) {
			propertyFocus.ask(owner.id, owner.properties);
			return;
		}
		await tick();
		document.getElementById(`card-${owner.id}`)?.focus();
	}

	// -- question types: add with a type, change a type (B13) ---------------------------
	let pickerOpen = $state(false);
	let picker = $state<{ mode: 'add'; page: string } | { mode: 'change'; id: string; current?: QuestionTypeId }>({
		mode: 'add',
		page: ''
	});
	let lastType = $state<QuestionTypeId | null>(lastUsedType());

	/** "Add question": pick a type for the given (or selected, or last) page. */
	function addQuestion(pageId?: string) {
		if (!store) return;
		const page = pageId ?? targetPage(pages, selection.id);
		if (!page) return toast('Add a page first.');
		picker = { mode: 'add', page };
		pickerOpen = true;
	}

	async function addQuestionOfType(type: QuestionTypeId, pageId?: string, index?: number) {
		if (!store) return;
		const page = pageId ?? targetPage(pages, selection.id);
		if (!page) return toast('Add a page first.');
		rememberType(type);
		lastType = type;
		const out = await store.submit([{ op: 'add_question', params: { page, type, ...(index !== undefined ? { index } : {}) } }]);
		if (out.status !== 'applied') return;
		const id = addedQuestionId(out.result.patch);
		if (id) {
			announce(`${questionTypeInfo(type)?.name ?? 'Question'} question added.`);
			// Select it and put the cursor in its text, ready to type.
			await goTo({ id, type: 'question', properties: ['label'] });
		}
	}

	// The toolbox under the outline (B16): click adds, drag inserts, Shift+Enter asks where.
	const typeDrag = new TypeDrag();
	let toolboxCollapsed = $state(false);
	let insertAtOpen = $state(false);
	let insertAtType = $state<QuestionTypeId | null>(null);
	let insertAtReturnId = $state<string | null>(null);

	function chooseWhere(type: QuestionTypeId) {
		insertAtType = type;
		const active = document.activeElement;
		insertAtReturnId = active instanceof HTMLElement && active.id ? active.id : null;
		insertAtOpen = true;
	}

	const selectedQuestion = () => {
		const n = selection.id ? findNode(pages, selection.id) : undefined;
		return n?.type === 'question' ? n : undefined;
	};

	let pickerReturnId = $state<string | null>(null);

	function openChangeType(id?: string) {
		if (!store) return;
		const n = id ? findNode(pages, id) : selectedQuestion();
		if (!n || n.type !== 'question') return toast('Select a question first.');
		picker = { mode: 'change', id: n.id, current: isQuestionType(n.questionType) ? n.questionType : undefined };
		const active = document.activeElement;
		pickerReturnId = active instanceof HTMLElement && active.id ? active.id : null;
		pickerOpen = true;
	}

	function onTypeChosen(type: QuestionTypeId) {
		const p = picker;
		if (p.mode === 'add') void addQuestionOfType(type, p.page);
		else void changeType(p.id, type);
	}

	// A type change that needs confirming (conflicting conditions, or published data).
	let typeChange = $state<TypeChangeRequest | null>(null);
	let resolveTypeChange: ((ok: boolean) => void) | null = null;
	function confirmTypeChange(r: TypeChangeRequest): Promise<boolean> {
		resolveTypeChange?.(false);
		typeChange = r;
		return new Promise((resolve) => (resolveTypeChange = resolve));
	}
	function onTypeChangeResolved(ok: boolean) {
		const r = resolveTypeChange;
		resolveTypeChange = null;
		typeChange = null;
		r?.(ok);
	}

	async function changeType(id: string, to: QuestionTypeId) {
		if (!store) return;
		const s = store;
		const fromType = findNode(pages, id)?.questionType;
		if (fromType === to) return;
		const from = questionTypeInfo(fromType)?.name ?? fromType ?? 'question';
		const toName = questionTypeInfo(to)?.name ?? to;
		const published = s.publishedVersions;
		const base = { from, to: toName, conflicts: 0, publishedVersions: published };
		if (published > 0 && !(await confirmTypeChange(base))) return announce('Type not changed.');
		const op = (force: boolean) => ({ op: 'change_question_type', params: { id, type: to, ...(force ? { force } : {}) } });
		let out = await s.submit([op(false)], { quiet: ['op.type_conflict'] });
		if (out.status === 'rejected' && out.diagnostics[0]?.code === 'op.type_conflict') {
			const conflicts = Math.max(1, out.diagnostics.length - 1);
			if (!(await confirmTypeChange({ ...base, conflicts }))) return announce('Type not changed.');
			out = await s.submit([op(true)]);
		}
		if (out.status === 'applied') announce(`Changed to ${toName}.`);
	}

	// -- pages and blocks: add, rename, duplicate, delete (B20) ---------------------------
	let menuTarget = $state<MenuTarget | null>(null);

	/** Select an item and focus it: its outline row if shown, else its canvas card. */
	async function focusItem(id: string) {
		selection.select(id);
		await tick();
		await tick();
		(document.getElementById(`outline-${id}`) ?? document.getElementById(`card-${id}`))?.focus();
	}

	const structure = new StructureActions({
		store: () => store,
		roots: () => pages,
		edit: (id, type, properties) => goTo({ id, type, properties }),
		focus: focusItem,
		language: () => defaultLanguage(store?.survey)
	});

	function openMenu(id: string, anchor: HTMLElement | null, point?: { x: number; y: number }) {
		if (!store || !editing) return;
		const node = findNode(pages, id);
		if (!node || node.type === 'survey') return;
		menuTarget = { id, label: node.label, anchor, point };
	}

	async function undoRedo(which: 'undo' | 'redo') {
		if (!store) return;
		const out = await (which === 'undo' ? store.undo() : store.redo());
		if (out.status === 'dropped') toast(out.message);
		else if (out.status === 'applied') announce(which === 'undo' ? 'Undone.' : 'Redone.');
	}

	/** Each view is its own page, at the host's URL for it (host/links.ts). */
	const routeOf = (v: BuilderView, hash?: string) => {
		if (store) {
			const id = store.surveyId;
			if (v === 'results') return optionalLink('results', { id }, { hash }) ?? link('editor', { id });
			const name = v === 'flow' || v === 'settings' || v === 'appearance' ? v : 'editor';
			return link(name, { id }, { hash });
		}
		// No survey: the lab's theme library, or the survey list (the mock shell in dev).
		return v === 'appearance' ? link('themes') : link('list');
	};
	const goto = (url: string) => leaveTo(url);

	let innerWidth = $state(1280);
	let outlineWidth = $state(280);
	let propertiesWidth = $state(320);
	let outlineOpen = $state(false);
	let propertiesOpen = $state(false);
	let paletteOpen = $state(false);
	let previewOpen = $state(false);
	// Switching view (Questions, Flow, Appearance) leaves the preview.
	$effect(() => {
		void view;
		untrack(() => (previewOpen = false));
	});

	const outlineCollapsible = $derived(editing && innerWidth < OUTLINE_BREAKPOINT);
	const propertiesCollapsible = $derived(editing && innerWidth < PROPERTIES_BREAKPOINT);
	const showOutline = $derived(!outlineCollapsible || outlineOpen);
	const showProperties = $derived(!propertiesCollapsible || propertiesOpen);
	// In the narrow outline overlay the toolbox starts folded, leaving the tree the room.
	$effect(() => {
		const narrow = outlineCollapsible;
		untrack(() => (toolboxCollapsed = narrow));
	});

	// Registered during init (not onMount) so child components see the shortcuts on first render.
	const offCommands = registry.registerAll(
		shellCommands({
				togglePalette: () => (paletteOpen = !paletteOpen),
			undo: () => {
				if (view === 'appearance') {
					if (!themeEditor.undo()) toast('Nothing to undo.');
				} else if (store) void undoRedo('undo');
				else toast('Undo: nothing to undo yet (editing is not connected).');
			},
			redo: () => {
				if (view === 'appearance') {
					if (!themeEditor.redo()) toast('Nothing to redo.');
				} else if (store) void undoRedo('redo');
				else toast('Redo: nothing to redo yet (editing is not connected).');
			},
			cyclePane: (dir) => cyclePane(dir),
			toggleTheme: () => theme.toggle(),
			systemTheme: () => theme.set('system'),
			toggleOutline: () => {
				outlineOpen = !outlineOpen;
				if (outlineOpen) propertiesOpen = false;
			},
			toggleProperties: () => {
				propertiesOpen = !propertiesOpen;
				if (propertiesOpen) outlineOpen = false;
			},
			outlineCollapsible: () => outlineCollapsible,
			propertiesCollapsible: () => propertiesCollapsible,
			preview: () => (previewOpen = true),
			clearSelection: () => selection.clear(),
			addQuestion: () => addQuestion(),
			addQuestionOfType: (t) => void addQuestionOfType(t),
			changeQuestionType: () => openChangeType(),
			canChangeType: () => editing && !!store && !!selectedQuestion(),
			canEdit: () => editing && !!store
		})
	);
	const offOutline = registry.register({
		id: 'outline.moveTo',
		label: 'Move to…',
		group: 'Edit',
		keywords: ['move', 'reorder', 'page', 'block'],
		enabled: canMoveSelection,
		run: () => (moveToOpen = true)
	});
	const offAppearance = registry.registerAll(
		appearanceCommands({
			view: () => view,
			open: (v) => goto(routeOf(v))
		})
	);
	const offStructure = registry.registerAll(
		structureCommands({
			canEdit: () => editing && !!store,
			canAddBlock: () => !!store && (editing || view === 'flow'),
			hasTarget: () => !!structure.typeOf(selection.id),
			addPage: () => void structure.addPage(selection.id),
			addBlock: () => (view === 'flow' ? requestAddBlock() : void structure.addBlock(selection.id)),
			rename: () => selection.id && structure.rename(selection.id),
			duplicate: () => selection.id && void structure.duplicate(selection.id),
			remove: () => selection.id && void structure.remove(selection.id)
		})
	);
	const offFlow = registry.registerAll(
		flowCommands({
			inFlow: () => view === 'flow',
			canOpen: () => !!store,
			open: () => goto(routeOf('flow')),
			addNode: requestAddNode
		})
	);
	// Survey settings and Publish (B12).
	let publishOpen = $state(false);
	const offSettings = registry.registerAll(
		settingsCommands({
			inSettings: () => view === 'settings',
			canOpen: () => !!store,
			open: () => goto(routeOf('settings')),
			publish: () => (publishOpen = true)
		})
	);

	// The Results page (V2), when the host serves it (its link is optional).
	const hasResults = $derived(!!store && optionalLink('results', { id: store.surveyId }) !== null);
	const offResults = registry.registerAll(
		resultsCommands({
			inResults: () => view === 'results',
			canOpen: () => hasResults,
			open: () => goto(routeOf('results'))
		})
	);
	// Loaded only on the Results page, so the editor's pages never fetch its code.
	const resultsView = $derived(view === 'results' && store ? import('../results/ResultsView.svelte') : null);

	/** A publish problem's link: the settings section, the Appearance view or the item. */
	async function goToProblem(p: PublishProblem) {
		if (!store) return;
		if (p.place.view === 'settings') {
			if (view === 'settings') {
				document.getElementById(`settings-${p.place.section}`)?.focus();
			} else {
				await goto(routeOf('settings', p.place.section || undefined));
			}
		} else if (p.place.view === 'appearance') {
			if (view !== 'appearance') await goto(routeOf('appearance'));
		} else {
			const owner = ownerOf(store.survey, p.place.pointer);
			// Another page (a full load): the editor selects the item from the URL's `#select=`.
			if (view !== 'editor') return void (await goto(routeOf('editor', `select=${owner.id}`)));
			await tick();
			await goTo(owner);
		}
	}

	onDestroy(() => {
		offResults();
		offSettings();
		offCommands();
		offAppearance();
		offFlow();
		offOutline();
		offStructure();
	});

	onMount(() => {
		const offTheme = theme.init();
		void health.check();
		// The canvas cards read the property schemas too (the properties pane may be closed).
		if (store) void propertySchemas.load(() => api.GET('/api/meta/property-schemas'));
		// Arrived from another page to look at one item (a publish problem): select it.
		const m = /^#select=(.+)$/.exec(location.hash);
		if (m && store && editing) {
			let id = '';
			try {
				id = decodeURIComponent(m[1]);
			} catch {
				// A malformed hash selects nothing.
			}
			const t = id ? findNode(pages, id)?.type : undefined;
			if (t === 'block' || t === 'page' || t === 'question') void goTo({ id, type: t, properties: [] });
		}
		return offTheme;
	});

	function closeOverlayOnEscape(e: KeyboardEvent, which: 'outline' | 'properties') {
		if (e.key !== 'Escape') return;
		// Escape in a dialog opened from the pane (portalled elsewhere) closes only the dialog.
		const pane = document.getElementById(which === 'outline' ? 'pane-outline' : 'pane-properties');
		if (!(e.target instanceof Node) || !pane?.contains(e.target)) return;
		// A dialog that has just opened may not have taken focus yet: Escape is still its.
		if (e.defaultPrevented || document.querySelector('[role="dialog"][data-state="open"]')) return;
		if (which === 'outline' && outlineCollapsible && outlineOpen) outlineOpen = false;
		if (which === 'properties' && propertiesCollapsible && propertiesOpen) propertiesOpen = false;
	}
</script>

<svelte:window bind:innerWidth onkeydown={(e) => registry.handleKeydown(e)} />

<div class="shell">
	<TopBar
		{title}
		saveState={store?.saveState ?? 'saved'}
		{view}
		viewTabs={!!store}
		results={hasResults}
		{registry}
		health={health.state}
		{outlineCollapsible}
		{propertiesCollapsible}
		{outlineOpen}
		{propertiesOpen}
	/>
	{#if store?.conflict}
		<ConflictBanner
			message={store.conflict.message}
			onreload={() => void store?.reload()}
			ondismiss={() => store?.dismissConflict()}
		/>
	{/if}

	{#if previewOpen && store}
		<main id="pane-preview" class="preview-pane" aria-labelledby="preview-heading">
			<PreviewPanel surveyId={store.surveyId} revision={store.revision} onclose={() => (previewOpen = false)} />
		</main>
	{:else if view === 'appearance'}
		<main id="pane-appearance" class="appearance" aria-label="Appearance">
			<AppearanceView {store} />
		</main>
	{:else if view === 'results' && store}
		<main id="pane-results" class="flow" aria-labelledby="results-heading">
			{#if resultsView}
				{#await resultsView}
					<p class="loading-view" role="status">Loading results…</p>
				{:then m}
					<m.default surveyId={store.surveyId} survey={store.survey} publishedVersions={store.publishedVersions} />
				{:catch}
					<p class="loading-view" role="alert">The results page could not be loaded. Reload to try again.</p>
				{/await}
			{/if}
		</main>
	{:else if view === 'settings' && store}
		<main id="pane-settings" class="flow" aria-labelledby="settings-heading">
			<SettingsView {store} />
		</main>
	{:else if view === 'flow' && store}
		<main id="pane-flow" class="flow" aria-labelledby="flow-heading">
			<FlowView {store} />
		</main>
	{:else}
	<div class="panes">
		{#if showOutline}
			<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
			<aside
				id="pane-outline"
				class="pane outline"
				class:overlay={outlineCollapsible}
				style:width={outlineCollapsible ? undefined : `${outlineWidth}px`}
				aria-labelledby="outline-heading"
				data-pane="outline"
				onkeydown={(e) => closeOverlayOnEscape(e, 'outline')}
			>
				<div class="outline-stack">
					<div class="pane-scroll">
						<h2 id="outline-heading" class="pane-heading">Outline</h2>
						{#key store?.surveyId}
							<OutlineTree
								roots={pages}
								{selection}
								multi={outlineSelection}
								onMove={store ? moveItems : undefined}
								typeDrag={store ? typeDrag : undefined}
								onContextMenu={store && editing ? openMenu : undefined}
							/>
						{/key}
						{#if store && editing}
							<OutlineActions
								actions={structure}
								selectedId={selection.id}
								selectedLabel={(selection.id && findNode(pages, selection.id)?.label) || ''}
								onmenu={(t) => (menuTarget = t)}
							/>
						{/if}
					</div>
					{#if store && editing}
						<TypeToolbox
							drag={typeDrag}
							bind:collapsed={toolboxCollapsed}
							onadd={(t) => void addQuestionOfType(t)}
							oninsert={(t, target) => void addQuestionOfType(t, target.parent ?? undefined, target.slot)}
							onchoosewhere={chooseWhere}
						/>
					{/if}
				</div>
				{#if !outlineCollapsible}
					<PaneResizer
						bind:size={outlineWidth}
						min={200}
						max={480}
						edge="left"
						label="Resize outline pane"
						controls="pane-outline"
					/>
				{/if}
			</aside>
		{/if}

		<main id="pane-canvas" class="pane canvas" aria-label="Canvas" data-pane="canvas">
			{#snippet addPageButton(page: { id: string; label: string })}
				<AddPageButton pageLabel={page.label} onclick={() => void structure.addPage(page.id)} />
			{/snippet}
			{#snippet canvasView()}
				<CanvasPane
					{pages}
					{selection}
					survey={store?.survey ?? null}
					schemas={propertySchemas.doc}
					mock={!store}
					onAddQuestion={store ? (id) => addQuestion(id) : undefined}
					afterPage={store ? addPageButton : undefined}
					onContextMenu={store ? openMenu : undefined}
					exportBadges={badges}
					onBadge={store ? (b) => void goTo(ownerOf(store.survey, b.pointer)) : undefined}
					diagnostics={store?.diagnostics ?? []}
					onDiagnostic={store ? (d) => void goTo(ownerOf(store.survey, d.pointer)) : undefined}
				/>
			{/snippet}
			{#snippet jsonView()}
				{#if jsonDraft}<JsonView draft={jsonDraft} />{/if}
			{/snippet}
			{#if store}
				<div class="canvas-tabs">
					<Tabs
						label="Editor view"
						bind:value={canvasTab}
						tabs={[
							{ value: 'canvas', label: 'Canvas', content: canvasView },
							{ value: 'json', label: 'JSON', content: jsonView }
						]}
					/>
				</div>
			{:else}
				{@render canvasView()}
			{/if}
			<!-- Inside a landmark; positioned fixed beside what opened it. -->
			{#if store}<StructureMenu bind:target={menuTarget} actions={structure} />{/if}
		</main>

		{#if showProperties}
			<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
			<aside
				id="pane-properties"
				class="pane properties"
				class:overlay={propertiesCollapsible}
				style:width={propertiesCollapsible ? undefined : `${propertiesWidth}px`}
				aria-labelledby="properties-heading"
				data-pane="properties"
				onkeydown={(e) => closeOverlayOnEscape(e, 'properties')}
			>
				{#if !propertiesCollapsible}
					<PaneResizer
						bind:size={propertiesWidth}
						min={240}
						max={520}
						edge="right"
						label="Resize properties pane"
						controls="pane-properties"
					/>
				{/if}
				<div class="pane-scroll">
					<PropertiesPane
						roots={pages}
						{selection}
						{store}
						onChangeType={store && editing ? (id) => openChangeType(id) : undefined}
					/>
				</div>
			</aside>
		{/if}
	</div>
	{#if store}
		<DiagnosticsStrip
			{store}
			check={exportCheck}
			bind:open={diagnosticsOpen}
			ongo={(item) => void goTo(item.owner)}
		/>
	{/if}
	{/if}
</div>

<CommandPalette bind:open={paletteOpen} {registry} />

{#if store}
	<PublishDialog {store} bind:open={publishOpen} ongo={(p) => void goToProblem(p)} />
	<TypePickerDialog
		bind:open={pickerOpen}
		mode={picker.mode}
		current={picker.mode === 'change' ? picker.current : undefined}
		lastUsed={lastType}
		returnFocusId={picker.mode === 'change' ? pickerReturnId : null}
		onchoose={onTypeChosen}
	/>
	<InsertAtDialog
		bind:open={insertAtOpen}
		type={insertAtType}
		roots={pages}
		selectedId={selection.id}
		returnFocusId={insertAtReturnId}
		oninsert={(t, target) => void addQuestionOfType(t, target.parent ?? undefined, target.slot)}
	/>
	<TypeChangeDialog request={typeChange} onresolve={onTypeChangeResolved} />
	<StructureDeleteDialog request={structure.deleteRequest} onresolve={(ok) => structure.resolveDelete(ok)} />
	<MoveToDialog bind:open={moveToOpen} roots={pages} ids={outlineSelection.ids} onMove={(ids, t) => void moveItems(ids, t)} />
{/if}

{#if !store}
	<Dialog
		bind:open={previewOpen}
		title="Preview"
		description="Preview runs a saved survey exactly as participants see it, with a debugger. Open a survey from Your surveys to preview it."
		size="sm"
	>
		{#snippet footer()}
			<Button variant="primary" onclick={() => (previewOpen = false)}>OK</Button>
		{/snippet}
	</Dialog>
{/if}

<Announcer />

<style>
	.shell {
		display: flex;
		flex-direction: column;
		height: 100dvh;
		overflow: hidden;
	}
	.preview-pane {
		display: flex;
		flex: 1;
		min-height: 0;
		min-width: 0;
	}
	.appearance,
	.flow {
		flex: 1;
		min-height: 0;
		overflow: hidden;
	}
	.flow {
		overflow: auto;
		background: var(--color-bg);
	}
	.loading-view {
		margin: 0;
		padding: var(--space-5) var(--space-4);
		color: var(--color-text-muted);
	}
	.panes {
		position: relative;
		display: flex;
		flex: 1;
		min-height: 0;
	}
	.pane {
		min-height: 0;
		overflow: auto;
	}
	.outline,
	.properties {
		display: flex;
		flex: none;
		overflow: visible;
		background: var(--color-surface);
	}
	.pane-scroll {
		flex: 1;
		min-width: 0;
		overflow: auto;
	}
	.outline-stack {
		display: flex;
		flex: 1;
		flex-direction: column;
		min-width: 0;
		min-height: 0;
	}
	.outline-stack > .pane-scroll {
		min-height: 6rem;
	}
	.outline-stack > :global(.toolbox) {
		flex: none;
		max-height: 50%;
		overflow: auto;
	}
	.outline {
		border-inline-end: 1px solid var(--color-border);
	}
	.properties {
		border-inline-start: 1px solid var(--color-border);
	}
	.canvas {
		flex: 1;
		min-width: 0;
		background: var(--color-bg);
	}
	.canvas-tabs :global(.osp-tabs-list) {
		position: sticky;
		top: 0;
		z-index: 5;
		padding-inline: var(--space-4);
		background: var(--color-bg);
	}
	.canvas-tabs :global(.osp-tabs-content) {
		padding-block: 0;
	}
	.overlay {
		position: absolute;
		inset-block: 0;
		z-index: 20;
		width: min(20rem, 85vw);
		box-shadow: var(--shadow-lg);
	}
	.outline.overlay {
		inset-inline-start: 0;
	}
	.properties.overlay {
		inset-inline-end: 0;
	}
	.pane-heading {
		margin: 0;
		padding: var(--space-3) var(--space-4) var(--space-1);
		font-size: var(--text-sm);
		font-weight: var(--weight-bold);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-text-muted);
	}
</style>
