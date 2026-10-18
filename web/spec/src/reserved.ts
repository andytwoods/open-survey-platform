/** Variable names a survey may not use, compared case-insensitively (osp_spec.reserved). */

export const RESERVED_NAMES: ReadonlySet<string> = new Set(
	[
		'id',
		'seed',
		'token',
		'submitdate',
		'lastpage',
		'startlanguage',
		'startdate',
		'datestamp',
		'ipaddr',
		'refurl',
		'instanceID',
		'instanceName',
		'deprecatedID',
		'meta'
	].map((n) => n.toLowerCase())
);

export const RESERVED_PREFIX = '_';
export const RESERVED_SUFFIX = '__state';

/** Why `name` is reserved, or null if it is free to use. */
export function reservedReason(name: string): string | null {
	const low = name.toLowerCase();
	if (RESERVED_NAMES.has(low)) return `'${name}' is a column name used by a runtime or export`;
	if (name.startsWith(RESERVED_PREFIX)) return `names starting with '${RESERVED_PREFIX}' are kept for platform columns`;
	if (low.endsWith(RESERVED_SUFFIX)) return `names ending in '${RESERVED_SUFFIX}' clash with CSV state columns`;
	return null;
}
