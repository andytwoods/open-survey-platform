// Connection indicator: the shell's only API call (GET /api/health via the generated client).
import { api } from './api';

export type HealthState = 'checking' | 'online' | 'offline';

class Health {
	state = $state<HealthState>('checking');

	async check(): Promise<HealthState> {
		this.state = 'checking';
		try {
			const { data, response } = await api.GET('/api/health');
			this.state = response.ok && data ? 'online' : 'offline';
		} catch {
			// No backend (static preview, network error, HTML fallback): offline, never a crash.
			this.state = 'offline';
		}
		return this.state;
	}
}

export const health = new Health();
