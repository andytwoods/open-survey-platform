import '@testing-library/svelte/vitest';
import { fireEvent, render, waitFor } from '@testing-library/svelte';
import axe from 'axe-core';
import { afterEach, describe, expect, it, vi } from 'vitest';
import fixture from '../properties/fixtures/property-schemas.json';

// The profile page against a mocked API: load, hide a property, add a custom property,
// save (the PUT body is the compacted profile), owner-only controls, axe.

const calls: { method: string; path: string; body?: unknown }[] = [];
let profile: Record<string, unknown> | null = null;
let canManage = true;

vi.mock('../api', () => ({
	api: {
		GET: vi.fn(async (path: string) => {
			calls.push({ method: 'GET', path });
			if (path === '/api/panel-profile')
				return { data: { tenantId: 't', profile, diagnostics: [], canManage, updatedBy: null }, response: { status: 200 } };
			if (path === '/api/meta/property-schemas') return { data: fixture, response: { status: 200 } };
			return { error: { message: 'no' }, response: { status: 404 } };
		}),
		PUT: vi.fn(async (path: string, opts: { body: { profile: Record<string, unknown> } }) => {
			calls.push({ method: 'PUT', path, body: opts.body.profile });
			profile = { profileVersion: 'osp-panel-profile/0.1', ...opts.body.profile };
			return { data: { tenantId: 't', profile, diagnostics: [], canManage, updatedBy: 'owner' }, response: { status: 200 } };
		}),
		DELETE: vi.fn(async (path: string) => {
			calls.push({ method: 'DELETE', path });
			profile = null;
			return { response: { status: 204 } };
		})
	}
}));

import ProfileView from './ProfileView.svelte';

afterEach(() => {
	calls.length = 0;
	profile = null;
	canManage = true;
});

async function setup() {
	const r = render(ProfileView);
	await waitFor(() => expect(r.container.querySelector('[data-testid="profile-type"]')).toBeTruthy());
	return r;
}

describe('ProfileView', () => {
	it('loads the stock schemas and the profile, hides a property and saves the compacted profile', async () => {
		const r = await setup();
		expect(r.getByTestId('profile-status').textContent).toContain('stock panel');
		const row = r.container.querySelector<HTMLElement>('.prop[data-key="choiceOrder"]')!;
		expect(row).toBeTruthy();
		const box = row.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
		expect(box.checked).toBe(true);
		await fireEvent.click(box);
		expect(row.dataset.hidden).toBe('true');
		// Required properties cannot be hidden.
		const label = r.container.querySelector<HTMLInputElement>('.prop[data-key="label"] input[type="checkbox"]')!;
		expect(label.disabled).toBe(true);
		// Move "required" up once.
		await fireEvent.click(r.getByLabelText('Move Required up'));
		await fireEvent.click(r.getByText('Save profile'));
		await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true));
		const body = calls.find((c) => c.method === 'PUT')!.body as { hidden: string[]; order: Record<string, string[]> };
		expect(body.hidden).toEqual(['single.choiceOrder']);
		expect(body.order.single.indexOf('required')).toBe(Object.keys(fixture.schemas.find((s) => s.type === 'single')!.properties).indexOf('required') - 1);
		await waitFor(() => expect(r.getByTestId('profile-message').textContent).toContain('saved'));
		expect(r.getByTestId('profile-status').textContent).toContain('own profile');
	});

	it('adds a custom property and refuses a bad key locally', async () => {
		const r = await setup();
		await fireEvent.click(r.getByText('Add custom property'));
		const rows = r.getAllByTestId('custom-row');
		expect(rows).toHaveLength(1);
		const key = rows[0].querySelector<HTMLInputElement>('input[id$="-key"]')!;
		await fireEvent.input(key, { target: { value: 'Bad Key' } });
		await fireEvent.click(r.getByText('Save profile'));
		expect(r.getByRole('alert').textContent).toMatch(/the key must be/);
		expect(calls.some((c) => c.method === 'PUT')).toBe(false);
		await fireEvent.input(key, { target: { value: 'construct' } });
		await fireEvent.input(rows[0].querySelector<HTMLInputElement>('input[id$="-label"]')!, { target: { value: 'Construct' } });
		await fireEvent.click(r.getByText('Save profile'));
		await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true));
		const body = calls.find((c) => c.method === 'PUT')!.body as { custom: unknown[] };
		expect(body.custom).toEqual([{ key: 'construct', kind: 'text', label: { en: 'Construct' }, group: 'Advanced' }]);
	});

	it('is read-only for non-owners and offers Remove profile to owners', async () => {
		canManage = false;
		profile = { hidden: ['*.help'] };
		const r = await setup();
		expect(r.getByTestId('profile-status').textContent).toContain('Only lab owners');
		expect((r.getByText('Save profile').closest('button') as HTMLButtonElement).disabled).toBe(true);
		expect(r.container.querySelector<HTMLInputElement>('.prop[data-key="help"] input')!.disabled).toBe(true);
		expect(r.queryByText('Remove profile…')).toBeNull();
		r.unmount();

		canManage = true;
		const o = await setup();
		await fireEvent.click(o.getByText('Remove profile…'));
		await fireEvent.click(o.getByText('Remove'));
		await waitFor(() => expect(calls.some((c) => c.method === 'DELETE')).toBe(true));
		await waitFor(() => expect(o.getByTestId('profile-status').textContent).toContain('stock panel'));
	});

	it('has no axe violations', async () => {
		profile = {
			custom: [{ key: 'scale', kind: 'choice', label: { en: 'Scale' }, options: [{ value: 'a', label: { en: 'A' } }] }]
		};
		const r = await setup();
		const results = await axe.run(r.container, { rules: { region: { enabled: false } } });
		expect(results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(', ')}`)).toEqual([]);
	});
});
