import { describe, expect, it } from 'vitest';
import { exportLinks, participantLink, placeOf, problemsOf, reproLink } from './model';

const d = (code: string, pointer: string, severity = 'error') => ({ code, pointer, severity, message: code });

describe('publish problems', () => {
	it('link each blocking problem to where it is fixed', () => {
		expect(placeOf(d('publish.retention_required', '/settings/retention')).place).toEqual({
			view: 'settings',
			section: 'retention'
		});
		expect(placeOf(d('theme.contrast', '/labTheme/colours/light/text')).place).toEqual({ view: 'appearance' });
		expect(placeOf(d('theme.contrast', '/settings/theme/colours/dark/accent')).place).toEqual({ view: 'appearance' });
		expect(placeOf(d('publish.consent_missing', '/consent', 'warning')).place).toEqual({
			view: 'settings',
			section: 'consent'
		});
		expect(placeOf(d('ref.unknown', '/blocks/0/pages/0/items/1/showIf')).place).toEqual({
			view: 'editor',
			pointer: '/blocks/0/pages/0/items/1/showIf'
		});
	});
	it('split errors from warnings (warnings never block)', () => {
		const { errors, warnings } = problemsOf([
			d('publish.retention_required', '/settings/retention'),
			d('publish.consent_missing', '/consent', 'warning'),
			d('choicelist.unused', '/choiceLists/0', 'info')
		]);
		expect(errors.map((e) => e.code)).toEqual(['publish.retention_required']);
		expect(warnings.map((e) => e.code)).toEqual(['publish.consent_missing']);
		expect(errors[0]!.action).toBe('Choose data retention');
	});
});

describe('links', () => {
	it('builds the participant link from the slug', () => {
		expect(participantLink('https://osp.example/', 'ab c')).toBe('https://osp.example/s/ab%20c');
	});
	it('lists the XLSForm and LSS exports', () => {
		expect(exportLinks('s1').map((x) => x.href)).toEqual([
			'/api/surveys/s1/export/xlsform',
			'/api/surveys/s1/export/lss'
		]);
	});
	it('shows the repro package only when /api/meta advertises it', () => {
		expect(reproLink(null, 's1', 2)).toBeNull();
		expect(reproLink({ features: {} }, 's1', 2)).toBeNull();
		expect(reproLink({ features: { reproPackage: true } }, 's1', 2)).toBe('/api/surveys/s1/versions/2/repro-package');
		expect(reproLink({ features: { reproPackage: '/api/repro/{surveyId}?v={version}' } }, 's1', 3)).toBe(
			'/api/repro/s1?v=3'
		);
		expect(reproLink({ features: { reproPackage: 'https://evil.example' } }, 's1', 3)).toBeNull();
	});
});
