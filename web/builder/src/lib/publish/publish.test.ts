import { describe, expect, it } from 'vitest';
import { exportLinks, osfNodeId, participantLink, placeOf, preregLinks, problemsOf, reproLink } from './model';

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
		expect(participantLink('https://osp.example/', '/r/?s=ab%20c')).toBe('https://osp.example/r/?s=ab%20c');
		expect(participantLink('https://osp.example', 'http://localhost:5174/r/?s=x')).toBe('http://localhost:5174/r/?s=x');
	});
	it('lists the XLSForm and LSS exports', () => {
		expect(exportLinks('s1').map((x) => x.href)).toEqual([
			'/api/surveys/s1/export/xlsform',
			'/api/surveys/s1/export/lss'
		]);
	});
	it('links the reproducibility package of the version', () => {
		expect(reproLink('s1', 2)).toBe('/api/surveys/s1/versions/2/repro-package');
	});
	it('links the preregistration bundle and summary of the version, under the API base', () => {
		expect(preregLinks('s1', 2)).toEqual({
			bundle: '/api/surveys/s1/versions/2/prereg-bundle',
			summary: '/api/surveys/s1/versions/2/prereg-summary'
		});
		expect(preregLinks('s/1', 3, 'https://host.example/osp/api').bundle).toBe(
			'https://host.example/osp/api/surveys/s%2F1/versions/3/prereg-bundle'
		);
	});
	it('reads an OSF project id from the id or a project URL', () => {
		expect(osfNodeId('ab3de')).toBe('ab3de');
		expect(osfNodeId('  https://osf.io/ab3de/ ')).toBe('ab3de');
		expect(osfNodeId('https://osf.io/ab3de/files/osfstorage')).toBe('ab3de');
		for (const bad of ['', 'a', 'ab 3de', '../x', 'https://osf.io/']) expect(osfNodeId(bad)).toBeNull();
	});
});
