// The builder's only route to the backend is the generated client in @osp/api-client.
import { createApiClient } from '@osp/api-client';

export const api = createApiClient({ baseUrl: '' });
