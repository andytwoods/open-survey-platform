/**
 * Every selected fixture script through the participant app (src/player.ts), compared with
 * its expected trace (src/evaluate.ts). One test per (fixture, script) and device project.
 *
 * - pending traces (non-empty `pending`) are played and reported, never failed;
 * - known runtime bugs (src/known.ts) are expected failures with an issue note;
 * - the verdict is attached as `verdict.json` for the report (src/reporter.ts).
 */
import { expect, test, type BrowserContextOptions } from '@playwright/test';
import { describe as describeVerdict, evaluate } from '../src/evaluate.ts';
import { casesOf, selectFixtures, variantKey } from '../src/fixtures.ts';
import { knownBug } from '../src/known.ts';
import { Player } from '../src/player.ts';

type Surveys = Record<string, { slugs: Record<string, string>; saveMode: string; error: string | null }>;
let surveys: Surveys | null = null;

const DEVICE_KEYS = ['viewport', 'screen', 'userAgent', 'deviceScaleFactor', 'isMobile', 'hasTouch'] as const;

function deviceOf(use: Record<string, unknown>): BrowserContextOptions {
	const device: BrowserContextOptions = {};
	for (const k of DEVICE_KEYS) if (use[k] !== undefined) (device as Record<string, unknown>)[k] = use[k];
	return device;
}

async function slugFor(baseURL: string, fixture: string, quotas?: Record<string, string>) {
	surveys ??= (await (await fetch(`${baseURL}/__harness/surveys`)).json()) as Surveys;
	return { entry: surveys[fixture], slug: surveys[fixture]?.slugs[variantKey(quotas)] };
}

// The harness itself: a wrong expected trace must fail, at the right paths.
test('harness self-check: a wrong trace is caught', async ({ browser, baseURL }, info) => {
	test.skip(info.project.name !== 'desktop-chromium', 'once is enough');
	const c = casesOf('06-clear-on-back').find((x) => x.script.id === 'main')!;
	const { slug } = await slugFor(baseURL!, c.fixture);
	const played = await new Player({ browser, baseURL: baseURL!, slug: slug!, device: deviceOf(info.project.use as Record<string, unknown>), script: c.script }).play();
	expect(evaluate(c, played).status).toBe('passed');
	const bad = structuredClone(c.expected);
	const step = bad.steps[5]!;
	(step.questions as Record<string, { state: string }>).pet_name!.state = 'answered';
	step.visible = ['pet_name', 'season'];
	(bad.response as { answers: Record<string, { value: unknown }> }).answers.season!.value = 'winter';
	const v = evaluate({ ...c, expected: bad }, played);
	expect(v.status).toBe('failed');
	expect(v.diffs.map((d) => d.path).sort()).toEqual([
		'response.answers.season.value',
		'steps[5].questions.pet_name.state',
		'steps[5].visible'
	]);
	expect(v.firstStep).toBe(5);
});

for (const fixture of selectFixtures()) {
	test.describe(fixture, () => {
		for (const c of casesOf(fixture)) {
			const pending = c.expected.pending.length > 0;
			test(`${c.script.id}${pending ? ' (pending)' : ''}`, async ({ browser, baseURL }, info) => {
				const known = knownBug(fixture, c.script.id, info.project.name);
				if (known) test.fail(true, known.issue);
				if (pending) info.annotations.push({ type: 'pending', description: c.expected.pending.join(', ') });

				const { entry, slug } = await slugFor(baseURL!, fixture, c.script.server?.quotas);
				if (!entry || entry.error || !slug) {
					const why = `fixture not published: ${entry?.error ?? 'no survey for this quota setting'}`;
					await info.attach('verdict.json', {
						body: JSON.stringify({ fixture, script: c.script.id, status: pending ? 'pending' : 'failed', abort: why, pending: c.expected.pending }),
						contentType: 'application/json'
					});
					if (!pending) throw new Error(why);
					return;
				}

				const device = deviceOf(info.project.use as Record<string, unknown>);
				const played = await new Player({ browser, baseURL: baseURL!, slug, device, script: c.script }).play();
				const verdict = evaluate(c, played);
				await info.attach('verdict.json', { body: JSON.stringify(verdict), contentType: 'application/json' });
				if (verdict.status === 'pending') return;
				expect(describeVerdict(verdict, 40), `${fixture}/${c.script.id}`).toEqual([]);
			});
		}
	});
}
