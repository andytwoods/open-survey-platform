/**
 * Presentation mode's URL flags (task V6), pure: `?present=1` opens the Results page with
 * only the cards (shareable, printable); `?layout=<id>` opens a saved layout.
 */
export const PRESENT_PARAM = 'present';
export const LAYOUT_PARAM = 'layout';

/** Whether a page URL's query asks for presentation mode. */
export function presentIn(search: string): boolean {
	const v = new URLSearchParams(search).get(PRESENT_PARAM);
	return v !== null && v !== '0' && v !== 'false';
}

/** The layout id a page URL's query names, if any. */
export function layoutIn(search: string): string | null {
	const v = new URLSearchParams(search).get(LAYOUT_PARAM);
	return v && /^[A-Za-z0-9_-]{1,64}$/.test(v) ? v : null;
}

/** `href` with the presentation flag set or cleared (the rest of the URL untouched). */
export function withPresent(href: string, on: boolean): string {
	const url = new URL(href);
	if (on) url.searchParams.set(PRESENT_PARAM, '1');
	else url.searchParams.delete(PRESENT_PARAM);
	return url.toString();
}
