/** "Run simulation" (task B11 on M1's `POST /api/surveys/{id}/simulate`). */
import type { components } from '@osp/api-client';
import { api } from '../api';

export type SimulationReport = components['schemas']['SimulationReport'];

export class SimulationRun {
	report = $state.raw<SimulationReport | null>(null);
	running = $state(false);
	error = $state<string | null>(null);

	async run(surveyId: string, n: number, seed: number) {
		this.running = true;
		this.error = null;
		try {
			const { data, error } = await api.POST('/api/surveys/{survey_id}/simulate', {
				params: { path: { survey_id: surveyId } },
				body: { n, seed, answerStrategy: 'uniform', quotaFull: 0.1, exhaustive: true }
			});
			if (data) this.report = data;
			else {
				const e = error as { message?: unknown; diagnostics?: Array<{ message?: string }> } | undefined;
				const extra = e?.diagnostics?.map((d) => d.message).filter(Boolean).join(' ');
				this.error = [typeof e?.message === 'string' ? e.message : 'The simulation failed.', extra].filter(Boolean).join(' ');
			}
		} catch (e) {
			this.error = (e as Error)?.message || 'Network error';
		} finally {
			this.running = false;
		}
	}
}

/** Nodes no simulated participant reached (from the warnings, else the node list). */
export function unreachable(r: SimulationReport): string[] {
	const w = r.warnings.filter((x) => x.code === 'node.unreachable' && x.target).map((x) => x.target!);
	return w.length ? w : r.nodes.filter((n) => !n.covered).map((n) => n.id);
}
