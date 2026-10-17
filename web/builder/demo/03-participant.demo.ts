import { expect, test, type Page } from '@playwright/test';
import { beat, caption, click, recordingContext, saveRecording, type } from './overlay';
import { createSurvey, DEMO_TITLE, demoSurvey, publishForParticipants } from './seed';

// Video 3: a participant. Desktop: consent, page 1, page 2, a refresh mid-page (nothing is
// lost), then "Continue on another device". Phone (390 × 844): the resume link opens the
// same session on page 2; finish (the follow-up question is shown because of 4 cups).
// Two recordings, joined by render.sh.

const CONSENT = {
	text: 'This invented study asks about coffee and sleep. Taking part is voluntary and you can stop at any time.',
	agreeLabel: 'I agree to take part',
	declineLabel: 'No thanks',
	declineOutcome: 'declined',
	countDeclines: true
};

const next = (page: Page) => click(page, page.getByRole('button', { name: 'Next' }));
const onPage = (page: Page, n: number) => expect(page.getByRole('heading', { level: 1 })).toContainText(`Page ${n}`);
const savedStatus = (page: Page) =>
	expect(page.getByTestId('save-status')).toHaveAttribute('data-status', 'saved', { timeout: 45_000 });

test('03 participant on desktop and phone', async ({ browser }) => {
	// Set up the published survey without recording.
	const setup = await browser.newContext();
	const sp = await setup.newPage();
	await sp.goto('/');
	const id = await createSurvey(sp, DEMO_TITLE, { ...demoSurvey(), consent: CONSENT });
	const link = await publishForParticipants(sp, id);
	await setup.close();

	// -- Desktop ----------------------------------------------------------------------
	const desktop = await recordingContext(browser, '03-participant-desktop');
	const page = await desktop.newPage();
	await page.goto(link);
	await expect(page.getByRole('button', { name: CONSENT.agreeLabel })).toBeVisible({ timeout: 30_000 });
	await caption(page, 'A participant opens the link on a laptop', 1800);
	await click(page, page.getByRole('button', { name: CONSENT.agreeLabel }));
	await onPage(page, 1);

	await caption(page, 'Answer page 1', 400);
	await type(page, page.getByLabel(/How many cups of coffee did you drink yesterday/), '4');
	await click(page, page.getByRole('radio', { name: 'With oat milk' }));
	await next(page);
	await onPage(page, 2);

	await caption(page, 'Page 2: a slider and a grid', 400);
	await type(page, page.getByLabel('Or type a number'), '7');
	await click(page, page.getByRole('radiogroup', { name: 'Weeknights' }).getByRole('radio', { name: 'OK' }));
	await savedStatus(page);
	await beat(page, 500);

	await caption(page, 'Refresh the page mid-way…', 900);
	await page.reload();
	await onPage(page, 2);
	await expect(page.getByLabel('Or type a number')).toHaveValue('7');
	await expect(page.getByRole('radiogroup', { name: 'Weeknights' }).getByRole('radio', { name: 'OK' })).toBeChecked();
	await caption(page, '…and nothing is lost', 1600);
	await click(page, page.getByRole('radiogroup', { name: 'At the weekend' }).getByRole('radio', { name: 'Well' }));
	await savedStatus(page);

	await caption(page, 'Continue on another device: a private resume link', 400);
	await click(page, page.getByText('Continue on another device', { exact: true }));
	const resume = page.getByTestId('resume-link');
	await expect(resume).toBeVisible();
	await resume.scrollIntoViewIfNeeded();
	const resumeLink = await resume.inputValue();
	expect(resumeLink).toContain('#resume=');
	await beat(page, 1800);
	await caption(page, '', 300);
	await saveRecording(desktop, page, '03-participant-desktop');

	// -- Phone ------------------------------------------------------------------------
	const phone = await recordingContext(browser, '03-participant-phone', {
		viewport: { width: 390, height: 844 },
		isMobile: true,
		hasTouch: true
	});
	const mobile = await phone.newPage();
	await mobile.goto(resumeLink);
	await onPage(mobile, 2);
	await expect(mobile.getByRole('radiogroup', { name: 'At the weekend' }).getByRole('radio', { name: 'Well' })).toBeChecked();
	await caption(mobile, 'On a phone, the resume link opens the same answers', 2000);
	await next(mobile);
	await onPage(mobile, 3);

	await caption(mobile, '4 cups: the follow-up question shows, with the answer piped in', 2200);
	await type(mobile, mobile.getByLabel(/What keeps you awake at night/), 'Late meetings and a noisy street.');
	const date = mobile.locator('[data-question="q-lie_in"]');
	await caption(mobile, 'A date', 300);
	await type(mobile, date.getByLabel('Day'), '12');
	await type(mobile, date.getByLabel('Month'), '9');
	await type(mobile, date.getByLabel('Year'), '2026');
	await next(mobile);
	await expect(mobile.getByTestId('thanks')).toBeVisible({ timeout: 45_000 });
	await caption(mobile, 'Submitted: one response, nothing lost or duplicated', 2200);
	await caption(mobile, '', 300);
	await saveRecording(phone, mobile, '03-participant-phone');
});
