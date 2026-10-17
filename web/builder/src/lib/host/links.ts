/**
 * All navigation between pages (planning/pages-split.md F2, D8). Each page is its own
 * entry at a URL the host chooses, so moving between them is a full page load built from
 * the host's link templates. Before leaving, the page flushes text buffers and waits for
 * the save queue to be acknowledged (at most 10 s, then asks); `beforeunload` warns while
 * edits are unsaved. Undo history is per page and resets on navigation.
 */
import { DEFAULT_LINKS, fillTemplate, type LinkName, type OspPageConfig } from './config';

export { DEFAULT_LINKS };

let config: OspPageConfig | null = null;

/** Set once by `mount` after validation. */
export function setPageConfig(c: OspPageConfig | null) {
	config = c;
}

export function pageConfig(): OspPageConfig | null {
	return config;
}

export interface LinkExtra {
	/** Without the leading `#`. */
	hash?: string;
	query?: Record<string, string>;
}

/** The URL of a page, from the host's template for it. */
export function link(name: LinkName, params: { id?: string } = {}, extra: LinkExtra = {}): string {
	return linkFrom(config?.links ?? DEFAULT_LINKS, name, params, extra);
}

/** Pure version of `link` (unit-tested). Query and hash keep the template's own. */
export function linkFrom(
	links: Readonly<Record<LinkName, string>>,
	name: LinkName,
	params: { id?: string } = {},
	extra: LinkExtra = {}
): string {
	let url = fillTemplate(links[name], params);
	const q = Object.entries(extra.query ?? {});
	if (q.length) {
		const hashAt = url.indexOf('#');
		const [path, hash] = hashAt < 0 ? [url, ''] : [url.slice(0, hashAt), url.slice(hashAt)];
		const qs = new URLSearchParams(q).toString();
		url = `${path}${path.includes('?') ? '&' : '?'}${qs}${hash}`;
	}
	if (extra.hash) url = `${url.replace(/#.*$/, '')}#${encodeURI(extra.hash).replace(/#/g, '%23')}`;
	return url;
}

// -- leaving a page -------------------------------------------------------------------

/** Something holding edits that are not acknowledged yet (the survey store). */
export interface SaveGuard {
	/** Edits queued or buffered and not yet acknowledged by the server. */
	unsaved(): boolean;
	/** Send buffered text now. */
	flush(): void;
	/** Resolves when the queue has drained (or can make no progress). */
	settled(): Promise<void>;
}

const guards = new Set<SaveGuard>();
let leaving = false;

export function registerSaveGuard(g: SaveGuard): () => void {
	guards.add(g);
	return () => guards.delete(g);
}

export function hasUnsaved(): boolean {
	return [...guards].some((g) => g.unsaved());
}

export const LEAVE_TIMEOUT_MS = 10_000;
export const LEAVE_QUESTION = 'Some of your changes have not been saved yet. Leave this page anyway?';

export interface LeaveDeps {
	assign: (url: string) => void;
	confirm: (question: string) => boolean;
	timeoutMs: number;
	sleep: (ms: number) => Promise<void>;
}

function browserDeps(): LeaveDeps {
	return {
		assign: (url) => location.assign(url),
		confirm: (q) => window.confirm(q),
		timeoutMs: LEAVE_TIMEOUT_MS,
		sleep: (ms) => new Promise((r) => setTimeout(r, ms))
	};
}

/**
 * Go to `url` (a full page load) once the save queue is acknowledged. Waits at most
 * `timeoutMs`, then asks; resolves false if the user chose to stay.
 */
export async function leaveTo(url: string, deps: Partial<LeaveDeps> = {}): Promise<boolean> {
	const d = { ...browserDeps(), ...deps };
	for (const g of guards) g.flush();
	if (hasUnsaved()) {
		const drained = Promise.all([...guards].map((g) => g.settled())).then(() => true);
		const ok = await Promise.race([drained, d.sleep(d.timeoutMs).then(() => false)]);
		if ((!ok || hasUnsaved()) && !d.confirm(LEAVE_QUESTION)) return false;
	}
	leaving = true;
	d.assign(url);
	return true;
}

/** Navigate to a page by name (see `link`). */
export function go(name: LinkName, params: { id?: string } = {}, extra: LinkExtra = {}): Promise<boolean> {
	return leaveTo(link(name, params, extra));
}

/** Warn on reload/close while edits are unsaved; flush buffered text when the page hides. */
export function installLeaveGuards(w: Window = window): () => void {
	const onBeforeUnload = (e: BeforeUnloadEvent) => {
		if (leaving || !hasUnsaved()) return;
		e.preventDefault();
		e.returnValue = '';
	};
	const onPageHide = () => {
		for (const g of guards) g.flush();
	};
	w.addEventListener('beforeunload', onBeforeUnload);
	w.addEventListener('pagehide', onPageHide);
	return () => {
		w.removeEventListener('beforeunload', onBeforeUnload);
		w.removeEventListener('pagehide', onPageHide);
	};
}

/** Tests only: forget guards and the leaving flag. */
export function resetLeaveState() {
	guards.clear();
	leaving = false;
}
