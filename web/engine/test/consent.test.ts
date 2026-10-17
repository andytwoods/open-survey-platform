/** The consent page (semantics.md §11, M5): before any question, agree / decline only. */
import { describe, expect, it } from 'vitest';
import {
	agree,
	awaitingConsent,
	CONSENT_PAGE,
	decline,
	declinedConsent,
	isState,
	next,
	restart,
	restore,
	result,
	snapshot,
	start,
	toPlain,
	tryAnswer,
	tryConsent,
	view,
	withChecksum,
	type Plan
} from '../src/index.ts';
import { clock, makePlan, q, t } from './helpers.ts';

function plan(): Plan {
	const base = makePlan({ pages: { p1: [q('a', 'integer')], p2: [q('b', 'text')] } });
	const { checksum: _c, ...rest } = base;
	return withChecksum({
		...rest,
		consent: {
			version: 'sha256:' + 'a'.repeat(64),
			text: t('Consent text'),
			agree: t('Yes'),
			decline: t('No'),
			declineOutcome: 'declined',
			countDeclines: false
		}
	});
}

const begin = (p = plan()) => start(p, { sessionSeed: 5, clock: clock(), urlParams: { PID: 'x' } });

describe('consent page', () => {
	it('is shown before any question, with nothing reached', () => {
		const s = begin();
		const v = view(s);
		expect(v.status).toBe('consent');
		expect(v.page).toBe(CONSENT_PAGE);
		expect(v.items).toEqual([]);
		expect(v.nav).toBeNull();
		expect(toPlain(v.consent!.text)).toBe('Consent text');
		expect(s.data.reachedPages).toEqual({});
		expect(awaitingConsent(s)).toBe(true);
	});

	it('refuses answers and Next until the participant decides', () => {
		const s = begin();
		expect(tryAnswer(s, 'a', 3).rejected).toBe('consent-pending');
		const n = next(s);
		expect(n.state).toBe(s);
		expect(n.result.outcome).toBe('invalid');
	});

	it('agree starts the flow and records version and time on the response', () => {
		const s = agree(begin());
		expect(view(s).page).toBe('p1');
		const r = result(s);
		expect(r.consentVersion).toBe('sha256:' + 'a'.repeat(64));
		expect(typeof r.consentedAt).toBe('number');
		expect(tryConsent(s, 'decline').rejected).toBe('no-consent'); // decided once
	});

	it('decline ends with the decline outcome and reaches no question', () => {
		const s = decline(begin());
		expect(view(s).status).toBe('ended');
		expect(result(s).end).toBe('declined');
		expect(result(s).consentVersion).toBeNull();
		expect(declinedConsent(s)).toBe(true);
		expect(Object.values(result(s).answers).every((a) => a.state === 'not-reached')).toBe(true);
	});

	it('survives restore, and a memory restart asks again', () => {
		const p = plan();
		const s = agree(begin(p));
		const back = restore(p, JSON.parse(JSON.stringify(snapshot(s))));
		expect(isState(back) ? view(back).page : back).toBe('p1');
		expect(view(restart(s)).status).toBe('consent');
	});

	it('a plan without consent is unchanged', () => {
		const p = makePlan({ pages: { p1: [q('a', 'integer')] } });
		const s = start(p, { sessionSeed: 5, clock: clock() });
		expect(view(s).status).toBe('page');
		expect(tryConsent(s, 'agree').rejected).toBe('no-consent');
		expect('consentVersion' in result(s)).toBe(false);
	});
});
