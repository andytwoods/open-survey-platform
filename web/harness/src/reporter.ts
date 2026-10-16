/**
 * Playwright reporter: the harness report, `.build/harness/report.md` and `report.json`.
 *
 * Per device project: passed / pending / failed / expected failures (known runtime bugs).
 * A script that passes in the engine runner (web/engine/.build/fixture-report.json, written
 * by `make engine-test`) but fails in the app is a **runtime divergence**: listed with the
 * fixture, script, first differing step and the action that led to it.
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import type { FullResult, Reporter, TestCase, TestResult } from '@playwright/test/reporter';
import { describe, type Verdict } from './evaluate.ts';
import { REPO } from './fixtures.ts';

type Outcome = 'passed' | 'pending' | 'failed' | 'expected-fail' | 'unexpected-pass';

interface Row {
	project: string;
	fixture: string;
	script: string;
	outcome: Outcome;
	verdict: Partial<Verdict> | null;
	error: string | null;
	ms: number;
	issue: string | null;
}

const OUT = join(REPO, '.build', 'harness');

function engineStatuses(): Map<string, string> {
	const path = join(REPO, 'web', 'engine', '.build', 'fixture-report.json');
	const m = new Map<string, string>();
	if (!existsSync(path)) return m;
	try {
		const r = JSON.parse(readFileSync(path, 'utf8')) as { scripts: Array<{ fixture: string; script: string; status: string }> };
		for (const s of r.scripts) m.set(`${s.fixture}/${s.script}`, s.status);
	} catch {
		/* no engine report: divergences are not classified */
	}
	return m;
}

export default class HarnessReporter implements Reporter {
	private rows: Row[] = [];
	private started = Date.now();

	onBegin() {
		// .build/ is scratch space (report, Playwright output): keep it out of git.
		mkdirSync(join(REPO, '.build'), { recursive: true });
		writeFileSync(join(REPO, '.build', '.gitignore'), '*\n');
	}

	onTestEnd(test: TestCase, result: TestResult) {
		if (result.status === 'skipped') return;
		const project = test.parent.project()?.name ?? '?';
		const [fixture = '?', title = '?'] = test.titlePath().slice(-2);
		const att = result.attachments.find((a) => a.name === 'verdict.json');
		let verdict: Partial<Verdict> | null = null;
		if (att?.body) {
			try {
				verdict = JSON.parse(att.body.toString('utf8')) as Partial<Verdict>;
			} catch {
				verdict = null;
			}
		}
		const issue = test.annotations.find((a) => a.type === 'fail')?.description ?? null;
		const pending = test.annotations.some((a) => a.type === 'pending') || verdict?.status === 'pending';
		let outcome: Outcome;
		if (test.expectedStatus === 'failed') outcome = result.status === 'failed' ? 'expected-fail' : 'unexpected-pass';
		else if (result.status === 'passed') outcome = pending ? 'pending' : 'passed';
		else outcome = 'failed';
		// Last retry wins.
		this.rows = this.rows.filter((r) => !(r.project === project && r.fixture === fixture && r.script === (verdict?.script ?? title)));
		this.rows.push({
			project,
			fixture,
			script: verdict?.script ?? title.replace(/ \(pending\)$/, ''),
			outcome,
			verdict,
			error: result.error?.message?.split('\n').slice(0, 6).join('\n') ?? null,
			ms: result.duration,
			issue
		});
	}

	onEnd(result: FullResult) {
		if (!this.rows.length) return;
		mkdirSync(OUT, { recursive: true });
		const engine = engineStatuses();
		const projects = [...new Set(this.rows.map((r) => r.project))].sort();
		const count = (p: string, o: Outcome) => this.rows.filter((r) => r.project === p && r.outcome === o).length;
		const bad = (r: Row) => r.outcome === 'failed' || r.outcome === 'expected-fail';
		const divergences = this.rows.filter((r) => bad(r) && engine.get(`${r.fixture}/${r.script}`) === 'passed');
		const otherFails = this.rows.filter((r) => bad(r) && engine.get(`${r.fixture}/${r.script}`) !== 'passed');

		const md: string[] = [];
		md.push('# Fixture harness report', '');
		md.push(
			`${new Date().toISOString()} · ${this.rows.length} runs · ${((Date.now() - this.started) / 1000).toFixed(0)} s · Playwright: ${result.status}`,
			''
		);
		md.push(
			engine.size
				? 'Engine runner status from `web/engine/.build/fixture-report.json`.'
				: 'No engine report (`make engine-test` not run): divergences are not classified.',
			''
		);
		md.push('## Per device', '', '| Device | Passed | Pending | Failed | Expected fail (known bug) | Unexpected pass |', '|---|--:|--:|--:|--:|--:|');
		for (const p of projects) {
			md.push(
				`| ${p} | ${count(p, 'passed')} | ${count(p, 'pending')} | ${count(p, 'failed')} | ${count(p, 'expected-fail')} | ${count(p, 'unexpected-pass')} |`
			);
		}
		md.push('', '## Runtime divergences (engine passes, app fails)', '');
		if (!divergences.length) md.push('None.');
		for (const r of divergences) md.push(...this.detail(r));
		md.push('', '## Other failures', '');
		if (!otherFails.length) md.push('None.');
		for (const r of otherFails) md.push(...this.detail(r, engine.get(`${r.fixture}/${r.script}`)));
		const up = this.rows.filter((r) => r.outcome === 'unexpected-pass');
		if (up.length) {
			md.push('', '## Known bugs that now pass (remove from src/known.ts)', '');
			for (const r of up) md.push(`- ${r.fixture}/${r.script} on ${r.project}: ${r.issue ?? ''}`);
		}
		md.push('', '## Pending (played, not asserted)', '');
		const pend = this.rows.filter((r) => r.outcome === 'pending');
		const byScript = new Map<string, Row[]>();
		for (const r of pend) byScript.set(`${r.fixture}/${r.script}`, [...(byScript.get(`${r.fixture}/${r.script}`) ?? []), r]);
		if (!byScript.size) md.push('None.');
		for (const [k, rs] of byScript) {
			const v = rs[0]!.verdict;
			const n = (v?.diffs?.length ?? 0) + (v?.problems?.length ?? 0) + (v?.invariants?.length ?? 0);
			md.push(`- ${k} (${(v?.pending ?? []).join(', ')}): ${v?.abort ? `could not play: ${v.abort}` : `${n} differences from the draft trace`} on ${rs.map((r) => r.project).join(', ')}`);
		}
		md.push('', '## All runs', '', '| Fixture | Script | ' + projects.join(' | ') + ' |', '|---|---|' + projects.map(() => '---|').join(''));
		const keys = [...new Set(this.rows.map((r) => `${r.fixture}\u0000${r.script}`))].sort();
		for (const k of keys) {
			const [f, s] = k.split('\u0000');
			const cells = projects.map((p) => {
				const r = this.rows.find((x) => x.project === p && x.fixture === f && x.script === s);
				return r ? `${r.outcome} (${(r.ms / 1000).toFixed(1)} s)` : '—';
			});
			md.push(`| ${f} | ${s} | ${cells.join(' | ')} |`);
		}
		writeFileSync(join(OUT, 'report.md'), md.join('\n') + '\n');
		writeFileSync(
			join(OUT, 'report.json'),
			JSON.stringify(
				{
					status: result.status,
					projects: Object.fromEntries(
						projects.map((p) => [
							p,
							Object.fromEntries((['passed', 'pending', 'failed', 'expected-fail', 'unexpected-pass'] as Outcome[]).map((o) => [o, count(p, o)]))
						])
					),
					divergences: divergences.map((r) => ({ project: r.project, fixture: r.fixture, script: r.script, step: r.verdict?.firstStep ?? null, action: r.verdict?.firstAction ?? null })),
					rows: this.rows
				},
				null,
				2
			)
		);
		const summary = projects
			.map((p) => `${p}: ${count(p, 'passed')} passed, ${count(p, 'pending')} pending, ${count(p, 'failed')} failed, ${count(p, 'expected-fail')} known`)
			.join('; ');
		console.log(`\nharness: ${summary}\nharness: ${divergences.length} runtime divergence(s); report in .build/harness/report.md`);
	}

	private detail(r: Row, engineStatus?: string): string[] {
		const v = r.verdict;
		const lines = [
			`### ${r.fixture} / ${r.script} on ${r.project}${r.outcome === 'expected-fail' ? ' (known)' : ''}`,
			''
		];
		if (r.issue) lines.push(`Issue: ${r.issue}`, '');
		if (engineStatus) lines.push(`Engine runner: ${engineStatus}.`, '');
		if (v?.firstStep !== undefined && v?.firstStep !== null) {
			lines.push(`First differing step: \`steps[${v.firstStep}]\`, after action ${v.firstStep - 1}: \`${JSON.stringify(v.firstAction)}\``, '');
		}
		const ds = v && v.diffs ? describe(v as Verdict, 15) : [];
		if (ds.length) lines.push('```text', ...ds, '```', '');
		else if (r.error) lines.push('```text', r.error, '```', '');
		return lines;
	}
}
