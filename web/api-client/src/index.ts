/**
 * Thin typed wrapper over openapi-fetch. The types in ./schema.d.ts are generated from
 * /contract/openapi.json by `make contract`: never edit them by hand.
 */
import createClient, { type ClientOptions } from 'openapi-fetch';
import type { paths } from './schema';

export type { components, operations, paths } from './schema';

export function createApiClient(options: ClientOptions = {}) {
	return createClient<paths>(options);
}

export type ApiClient = ReturnType<typeof createApiClient>;
