/**
 * The property schemas (`GET /api/meta/property-schemas`), fetched once per page load and
 * shared by every panel, plus `schemaFor`: which schema describes a selected object.
 */
import type { PropertySchemasDoc, TypeSchema } from './types';

type Fetcher = () => Promise<{ data?: unknown; error?: unknown }>;

function isDoc(v: unknown): v is PropertySchemasDoc {
	return (
		typeof v === 'object' &&
		v !== null &&
		Array.isArray((v as PropertySchemasDoc).schemas) &&
		Array.isArray((v as PropertySchemasDoc).groups)
	);
}

export class PropertySchemas {
	doc = $state.raw<PropertySchemasDoc | null>(null);
	error = $state<string | null>(null);
	#loading: Promise<void> | null = null;

	/** Fetch once (later calls reuse the result; a failure can be retried). */
	load(fetcher: Fetcher): Promise<void> {
		if (this.doc) return Promise.resolve();
		this.#loading ??= fetcher()
			.then(({ data }) => {
				if (isDoc(data)) {
					this.doc = data;
					this.error = null;
				} else {
					this.error = 'Property schemas could not be loaded.';
				}
			})
			.catch(() => {
				this.error = 'Property schemas could not be loaded.';
			})
			.finally(() => {
				this.#loading = null;
			});
		return this.#loading;
	}
}

export const propertySchemas = new PropertySchemas();

/**
 * The schema for a selected object: questions by their `type`, pages, blocks and the
 * survey by entity. Undefined when the document has none (e.g. an unknown question type).
 */
export function schemaFor(
	doc: PropertySchemasDoc | null,
	entity: 'question' | 'page' | 'block' | 'survey',
	object: unknown
): TypeSchema | undefined {
	if (!doc) return undefined;
	if (entity === 'question') {
		const type = (object as { type?: unknown } | null)?.type;
		return doc.schemas.find((s) => s.entity === 'question' && s.type === type);
	}
	return doc.schemas.find((s) => s.entity === entity);
}
