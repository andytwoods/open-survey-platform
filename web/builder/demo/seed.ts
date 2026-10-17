import { expect, type Page } from '@playwright/test';

/**
 * The invented demo survey ("Coffee and sleep study") and the API calls that set it up.
 * Every question and answer here is made up: no real personal data (AGENTS.md rule 7).
 */
export const DEMO_TITLE = 'Coffee and sleep study';

const cups = { kind: 'ref', id: 'cups' };

export function demoSurvey() {
	return {
		specVersion: 'osp-survey/0.1',
		id: 'coffee_sleep',
		version: 1,
		metadata: { title: DEMO_TITLE, languages: ['en'] },
		settings: { backNavigation: true },
		choiceLists: [
			{
				id: 'how_taken',
				choices: [
					{ value: 1, label: 'Black' },
					{ value: 2, label: 'With milk' },
					{ value: 3, label: 'With oat milk' },
					{ value: 4, label: 'I do not drink coffee' }
				]
			},
			{
				id: 'quality',
				choices: [
					{ value: 1, label: 'Badly' },
					{ value: 2, label: 'OK' },
					{ value: 3, label: 'Well' }
				]
			}
		],
		blocks: [
			{
				id: 'coffee',
				title: 'Coffee',
				pages: [
					{
						id: 'p_coffee',
						title: 'Coffee',
						items: [
							{ type: 'note', id: 'intro', label: 'Thanks for helping with this (invented) study. It takes about two minutes.' },
							{ type: 'integer', id: 'cups', label: 'How many cups of coffee did you drink yesterday?', required: true },
							{ type: 'single', id: 'taken', label: 'How do you usually take your coffee?', choiceList: 'how_taken', required: true }
						]
					}
				]
			},
			{
				id: 'sleep',
				title: 'Sleep',
				pages: [
					{
						id: 'p_sleep',
						title: 'Sleep',
						items: [
							{
								type: 'slider',
								id: 'sleepy',
								label: 'How sleepy do you feel right now?',
								min: 0,
								max: 10,
								step: 1,
								minLabel: 'Wide awake',
								maxLabel: 'Very sleepy'
							},
							{
								type: 'matrix',
								id: 'nights',
								label: 'How well did you sleep this week?',
								rows: [
									{ id: 'weeknights', label: 'Weeknights' },
									{ id: 'weekend', label: 'At the weekend' }
								],
								choiceList: 'quality'
							}
						]
					},
					{
						id: 'p_more',
						title: 'A little more',
						items: [
							{
								type: 'text',
								id: 'awake',
								label: 'You had ${cups} cups yesterday. What keeps you awake at night?',
								showIf: { kind: 'compare', op: '>=', left: cups, right: { kind: 'int', value: 3 } }
							},
							{ type: 'date', id: 'lie_in', label: 'When did you last have a lie-in?' }
						]
					}
				]
			}
		],
		flow: [
			{ type: 'block', id: 'n_coffee', block: 'coffee' },
			{ type: 'block', id: 'n_sleep', block: 'sleep' },
			{ type: 'end', id: 'n_end' }
		]
	};
}

/** Origin header for the demo's own API writes (osp-api checks it on unsafe requests). */
function headers(page: Page) {
	return { Origin: new URL(page.url()).origin };
}

/** Create a survey through the API; returns its id. The page must be on the builder. */
export async function createSurvey(page: Page, title: string, survey: unknown = demoSurvey()): Promise<string> {
	const r = await page.request.post('/api/surveys', { headers: headers(page), data: { title, survey } });
	expect(r.status(), await r.text()).toBe(201);
	return ((await r.json()) as { id: string }).id;
}

/** Apply ops to a draft through the API (as another client would). */
export async function applyOps(page: Page, id: string, ops: unknown[]) {
	const detail = (await (await page.request.get(`/api/surveys/${id}`)).json()) as { revision: number };
	const r = await page.request.post(`/api/surveys/${id}/ops`, {
		headers: headers(page),
		data: { baseRevision: detail.revision, ops }
	});
	expect(r.status(), await r.text()).toBe(200);
}

/** Retention + consent, then publish: returns the participant link. */
export async function publishForParticipants(page: Page, id: string): Promise<string> {
	await applyOps(page, id, [
		{ op: 'set_property', params: { target: '/settings', property: 'retention', value: { kind: 'days-after-close', days: 365 } } }
	]);
	const r = await page.request.post(`/api/surveys/${id}/publish`, { headers: headers(page) });
	expect(r.status(), await r.text()).toBe(201);
	const detail = (await (await page.request.get(`/api/surveys/${id}`)).json()) as { publicSlug: string };
	return new URL(`/s/${detail.publicSlug}`, page.url()).toString();
}
