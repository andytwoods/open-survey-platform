/**
 * External task step (task EX2, planning/external-tasks.md), against the real backend: the
 * participant is handed off to the (stubbed) task host with a piped id, the platform's
 * `osp_return` and a signed `osp_token`; on return the token is verified and the value the
 * task carried back is captured into a variable and shown on the next page. A forged return
 * token (never minted by the server) does not let the participant skip the task.
 */
import { expect, test, type Page } from '@playwright/test';
import { onPage, next, slugOf } from './helpers';

const TASK = 'https://run.pavlovia.org/lab/e';

/** Catch the top-level navigation to the external task; capture its URL, serve a stub page. */
async function catchTask(page: Page) {
	const seen: string[] = [];
	await page.route(`${TASK}**`, async (route) => {
		seen.push(route.request().url());
		await route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><title>Task</title><h1>Task</h1>' });
	});
	return seen;
}

async function openAt(page: Page, name: string, query = '') {
	await page.goto(`/s/${await slugOf(page, name)}${query}`);
}

test('hands off with osp_return + osp_token and resumes with the returned value on return', async ({ page }) => {
	const seen = await catchTask(page);
	await openAt(page, 'external', '?PROLIFIC_PID=p9');
	await onPage(page, 1);
	await page.getByLabel('What is your first name?').fill('Sam');
	await next(page);

	// The tab navigated to the task with the piped id, the return URL and a signed token.
	await page.waitForURL(`${TASK}**`, { timeout: 15_000 });
	expect(seen).toHaveLength(1);
	const url = new URL(seen[0]!);
	expect(url.searchParams.get('pid')).toBe('p9');
	const ospReturn = url.searchParams.get('osp_return')!;
	const ospToken = url.searchParams.get('osp_token')!;
	expect(ospToken).toBeTruthy();
	expect(ospReturn).toContain('/s/');

	// The task sends the participant back with the token and a return value.
	await page.goto(`${ospReturn}&osp_token=${encodeURIComponent(ospToken)}&rt=742`);
	await onPage(page, 2);
	await expect(page.getByText('Your task score was 742.')).toBeVisible();
});

test('a forged return token cannot skip the task: the participant is sent to it', async ({ page }) => {
	const seen = await catchTask(page);
	await openAt(page, 'external', '?PROLIFIC_PID=p9');
	await onPage(page, 1);
	await page.getByLabel('What is your first name?').fill('Sam');
	await next(page);
	await page.waitForURL(`${TASK}**`, { timeout: 15_000 });
	const ospReturn = new URL(seen[0]!).searchParams.get('osp_return')!;

	// Return with a made-up token: the server rejects it and the app hands off again.
	seen.length = 0;
	await page.goto(`${ospReturn}&osp_token=not.a.real.token&rt=999`);
	await page.waitForURL(`${TASK}**`, { timeout: 15_000 });
	expect(seen.length).toBeGreaterThan(0); // sent back to the task, not advanced to page 2
});
