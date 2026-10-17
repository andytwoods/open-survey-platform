/**
 * How a page entry starts (planning/pages-split.md F1). Every entry in `src/pages/` exports
 * `mount(el, config)` built here, and auto-mounts when its document has
 * `<div id="osp">` and `<script type="application/json" id="osp-config">`.
 *
 * The config is validated first (config.ts). A bad config is rejected: nothing runs, the
 * element shows why, and `mount` throws `OspConfigError`.
 */
import '@osp/ui-components/tokens.css';
import { mount as mountComponent, unmount, type Component } from 'svelte';
import { parseConfig, parseFrameConfig, type OspPageConfig } from './config';
import { hasUnsaved, installLeaveGuards, setPageConfig } from './links';
import PageRoot from './PageRoot.svelte';
import { session } from './session.svelte';

export const CONFIG_ID = 'osp-config';
export const ROOT_ID = 'osp';

export class OspConfigError extends Error {
	constructor(readonly errors: string[]) {
		super(`Invalid osp page config: ${errors.join('; ')}`);
		this.name = 'OspConfigError';
	}
}

export interface MountedPage {
	unmount(): void;
}

export type MountPage = (el: HTMLElement, config: unknown) => MountedPage;

export interface PageSpec {
	/** Page name, as in the manifest. */
	name: string;
	// Pages take different props; `props` below builds them from the config.
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	component: Component<any>;
	props?: (config: OspPageConfig) => Record<string, unknown>;
	/** Survey-scoped: `surveyId` is required. */
	survey?: boolean;
	/** Ask `GET /api/me` who this is (header name, lab choice). Default true. */
	identity?: boolean;
}

function showErrors(el: HTMLElement, name: string, errors: string[]) {
	el.replaceChildren();
	const box = document.createElement('div');
	box.setAttribute('role', 'alert');
	box.dataset.ospConfigError = name;
	const p = document.createElement('p');
	p.textContent = `This page (${name}) could not start: its configuration is invalid.`;
	const ul = document.createElement('ul');
	for (const e of errors) {
		const li = document.createElement('li');
		li.textContent = e;
		ul.append(li);
	}
	box.append(p, ul);
	el.append(box);
}

/** The `mount` of a builder page. */
export function definePage(spec: PageSpec): MountPage {
	return (el, raw) => {
		const parsed = parseConfig(raw, location.origin, { requireSurveyId: spec.survey });
		if (!parsed.ok) {
			showErrors(el, spec.name, parsed.errors);
			throw new OspConfigError(parsed.errors);
		}
		const config = parsed.config;
		setPageConfig(config);
		session.configure(config.onUnauthenticated, { unsaved: hasUnsaved });
		const offGuards = installLeaveGuards(window);
		const app = mountComponent(PageRoot, {
			target: el,
			props: {
				page: spec.component,
				pageProps: spec.props?.(config) ?? {},
				identity: spec.identity ?? true
			}
		});
		return {
			unmount() {
				offGuards();
				void unmount(app);
				setPageConfig(null);
			}
		};
	};
}

/** The `mount` of the preview frame: no API base, no CSRF, no session (D10). */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function defineFramePage(name: string, component: Component<any>): MountPage {
	return (el, raw) => {
		const parsed = parseFrameConfig(raw);
		if (!parsed.ok) {
			showErrors(el, name, parsed.errors);
			throw new OspConfigError(parsed.errors);
		}
		const app = mountComponent(component, { target: el, props: {} });
		return { unmount: () => void unmount(app) };
	};
}

/** Read the config tag (null if absent; an invalid-JSON tag is reported as a config error). */
export function readConfigTag(doc: Document = document): { found: boolean; value: unknown; error?: string } {
	const tag = doc.getElementById(CONFIG_ID);
	if (!tag) return { found: false, value: undefined };
	if (tag.getAttribute('type') !== 'application/json') {
		return { found: true, value: undefined, error: 'config tag: must be <script type="application/json">' };
	}
	try {
		return { found: true, value: JSON.parse(tag.textContent ?? '') };
	} catch {
		return { found: true, value: undefined, error: 'config tag: not valid JSON' };
	}
}

/**
 * Mount into `#osp` from the config tag, if the document has both. `frame` pages also
 * mount without a config tag.
 */
export function autoMount(mount: MountPage, opts: { name: string; frame?: boolean }): MountedPage | null {
	if (typeof document === 'undefined') return null;
	const el = document.getElementById(ROOT_ID);
	const tag = readConfigTag();
	if (!el || (!tag.found && !opts.frame)) return null;
	if (tag.error) {
		showErrors(el, opts.name, [tag.error]);
		console.error(new OspConfigError([tag.error]));
		return null;
	}
	try {
		return mount(el, tag.value);
	} catch (e) {
		console.error(e);
		return null;
	}
}
