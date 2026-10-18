/**
 * The serverless demo's API (task DEMO2): every call the builder's generated client makes
 * is answered here, in the page (api.ts `setLocalBackend`). Nothing reaches a network.
 *
 * - The survey: `GET /api/surveys[/{id}]` and `PUT …/draft` (the builder applies its edits,
 *   undo and redo itself with @osp/ops and saves the patch, CE5) go to a
 *   `MemorySurveyTransport` (@osp/spec diagnostics). Preview and condition text are
 *   compiled and parsed by the builder itself, so `/preview-plan` and `/meta/expressions`
 *   are not called.
 * - Static metadata (property schemas, retention options, version, health, identity, panel
 *   profile, themes, the bundled bank instruments) comes from `DemoData`, generated at
 *   build time from the Python packages through the real API (scripts/demo_data.py).
 * - Anything that needs a real server (publish, results, imports, exports, OSF, saving to
 *   or sharing the bank, the theme library, simulations) answers 501 with a friendly
 *   "not available in the demo" message the pages show as they show any refusal.
 */
import type { MemorySurveyTransport } from './memory-transport';
import type { Result } from '../sync/transport';

export const DEMO_UNAVAILABLE_CODE = 'demo.unavailable';
export const DEMO_UNAVAILABLE =
	'Not available in the demo: it runs entirely in your browser. Install Open Survey Platform to try this.';

/** scripts/demo_data.py's output (web/builder/demo-site/public/data/demo-data.json). */
export interface DemoData {
	version: 1;
	/** Static GET answers by API path. */
	get: Record<string, unknown>;
	/** `GET /api/bank?pageSize=200`: the bundled library as the bank search lists it. */
	bankList: { items: BankSummary[] } & Record<string, unknown>;
	/** `GET /api/bank/{id}` for every bundled instrument. */
	bankItems: Record<string, unknown>;
	/** The theme presets (osp_spec.theme.PRESETS). */
	presets: Record<string, unknown>;
}

interface BankSummary {
	id: string;
	kind?: string;
	source?: string;
	title?: string;
	abbreviation?: string | null;
	description?: string | null;
	tags?: string[];
	languages?: string[];
	licenceClass?: string | null;
	[k: string]: unknown;
}

const json = (status: number, body: unknown): Response =>
	new Response(status === 204 ? null : JSON.stringify(body), {
		status,
		headers: { 'content-type': 'application/json' }
	});

export const unavailable = (): Response => json(501, { code: DEMO_UNAVAILABLE_CODE, message: DEMO_UNAVAILABLE });
const notFound = (message = 'Not found.'): Response => json(404, { code: 'not_found', message });

function fromResult<T>(r: Result<T>): Response {
	switch (r.kind) {
		case 'ok':
			return json(200, r.data);
		case 'conflict':
			return json(409, { code: 'conflict', message: r.message, currentRevision: r.currentRevision });
		case 'rejected':
			return json(422, { code: 'rejected', message: r.message, diagnostics: r.diagnostics, failedIndex: r.failedIndex });
		case 'offline':
			return json(503, { code: 'offline', message: r.message });
		default:
			return json(r.status, { code: r.code, message: r.message });
	}
}

async function body(request: Request): Promise<Record<string, unknown>> {
	try {
		const b = (await request.json()) as unknown;
		return typeof b === 'object' && b !== null && !Array.isArray(b) ? (b as Record<string, unknown>) : {};
	} catch {
		return {};
	}
}

const words = (s: string) => s.toLowerCase().split(/\s+/).filter(Boolean);

/** `GET /api/bank` over the bundled library: every word must match; the filters as the API's. */
function searchBank(data: DemoData, q: URLSearchParams): unknown {
	const all = data.bankList.items ?? [];
	const want = words(q.get('q') ?? '');
	const kind = q.get('kind');
	const source = q.get('source');
	const lang = q.get('lang');
	const licence = q.get('licence');
	const tags = q.getAll('tag');
	const items = all.filter((s) => {
		const hay = [s.title, s.abbreviation, s.description, ...(s.tags ?? [])].filter(Boolean).join(' ').toLowerCase();
		if (!want.every((w) => hay.includes(w))) return false;
		if (kind && s.kind !== kind) return false;
		if (source && s.source !== source) return false;
		if (lang && !(s.languages ?? []).includes(lang)) return false;
		if (licence && s.licenceClass !== licence) return false;
		return tags.every((t) => (s.tags ?? []).includes(t));
	});
	const pageSize = Math.min(200, Math.max(1, Number(q.get('pageSize') ?? 50) || 50));
	const page = Math.max(1, Number(q.get('page') ?? 1) || 1);
	return {
		...data.bankList,
		items: items.slice((page - 1) * pageSize, page * pageSize),
		total: items.length,
		page,
		pageSize,
		// The demo lab can insert bundled instruments but not save, edit or share.
		canManage: false,
		canShare: false,
		hostSharing: false
	};
}

const STATIC_GETS = [
	'/api/health',
	'/api/version',
	'/api/me',
	'/api/meta/property-schemas',
	'/api/meta/retention',
	'/api/panel-profile',
	'/api/panel-profile/schemas',
	'/api/bank/library',
	'/api/bank/stubs'
];

export interface DemoBackendOptions {
	data: DemoData;
	transport: MemorySurveyTransport;
	/** The demo survey's list entry and detail fields beyond the draft. */
	createdAt?: string;
}

/** The demo's answer to one request of the generated client. Never throws. */
export function createDemoBackend(opts: DemoBackendOptions): (request: Request) => Promise<Response> {
	const { data, transport } = opts;
	const at = opts.createdAt ?? new Date().toISOString();
	const me = (data.get['/api/me'] ?? {}) as { userId?: string; memberships?: { tenantId?: string }[] };
	const tenantId = me.memberships?.[0]?.tenantId ?? 'demo-lab';
	const userId = me.userId ?? 'demo-researcher';

	const summary = () => {
		const d = transport.draft;
		return { id: d.id, tenantId, title: d.title, createdBy: userId, createdAt: at, closedAt: null, publicSlug: null };
	};
	const detail = () => {
		const d = transport.draft;
		return {
			...summary(),
			revision: d.revision,
			survey: d.survey,
			updatedAt: at,
			updatedBy: userId,
			diagnostics: transport.diagnostics(),
			publishedVersions: 0
		};
	};

	async function route(request: Request): Promise<Response> {
		const url = new URL(request.url);
		const path = url.pathname.replace(/\/+$/, '');
		const method = request.method.toUpperCase();
		const id = transport.draft.id;

		if (method === 'GET') {
			if (STATIC_GETS.includes(path) && path in data.get) return json(200, data.get[path]);
			if (path === '/api/themes') {
				const t = (data.get['/api/themes'] ?? {}) as Record<string, unknown>;
				return json(200, { themes: [], defaultThemeId: null, ...t, tenantId, canManage: false });
			}
			if (path === '/api/surveys') return json(200, [summary()]);
			if (path === '/api/bank') return json(200, searchBank(data, url.searchParams));
			const bank = /^\/api\/bank\/([^/]+)$/.exec(path);
			if (bank && bank[1] !== 'library' && bank[1] !== 'stubs') {
				const item = data.bankItems[decodeURIComponent(bank[1])];
				return item ? json(200, item) : notFound('Bank item not found.');
			}
		}

		const s = /^\/api\/surveys\/([^/]+)(\/.*)?$/.exec(path);
		if (s) {
			const sid = decodeURIComponent(s[1]);
			const rest = s[2] ?? '';
			// Imports (`/api/surveys/import…`) and other labs' surveys: not here.
			if (sid !== id) return method === 'GET' && rest === '' ? notFound('Survey not found.') : unavailable();
			if (method === 'GET' && rest === '') return json(200, detail());
			if (method === 'PUT' && rest === '/draft') {
				const b = await body(request);
				return fromResult(
					await transport.saveDraft(sid, {
						baseRevision: b.baseRevision as number,
						patch: (Array.isArray(b.patch) ? b.patch : []) as never,
						ops: (Array.isArray(b.ops) ? b.ops : []) as never,
						transactionId: b.transactionId as string
					})
				);
			}
			return unavailable();
		}

		return unavailable();
	}

	return async (request) => {
		try {
			return await route(request);
		} catch (e) {
			// Rule 3: never crash on input. A bug here is a 500, like a server's.
			console.error('demo backend', e);
			return json(500, { code: 'internal', message: 'Something went wrong in the demo.' });
		}
	};
}
