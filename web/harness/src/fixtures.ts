/** Fixture files (fixtures/FORMAT.md) and which of them a run selects. */
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import type { Invariant } from './compare.ts';

export const REPO = resolve(import.meta.dirname, '../../..');
export const FIXTURES = join(REPO, 'fixtures');

export type QuotaFate = 'timeout' | 'lostReply' | 'ok';

export interface Server {
	conditions?: Record<string, string | number>;
	quotas?: Record<string, string>;
	quotaCalls?: Record<string, QuotaFate[]>;
}

export interface Action {
	expectPage?: string;
	set?: Record<string, unknown>;
	setIfShown?: Record<string, unknown>;
	do: 'next' | 'back' | 'refresh' | 'resume' | 'retry' | 'switchDevice' | 'offline' | 'online';
	device?: string;
	restoreFrom?: 'local';
}

export interface Script {
	id: string;
	description?: string;
	sessionSeed: number;
	language: string;
	server?: Server;
	storage?: 'blocked';
	replay?: { server?: Server };
	actions: Action[];
}

export interface Expected {
	pending: string[];
	steps: Array<Record<string, unknown>>;
	invariants: Invariant[];
	response: Record<string, unknown> | string;
	network?: Record<string, unknown>;
}

export interface Case {
	fixture: string;
	file: string;
	script: Script;
	expected: Expected;
}

function json<T>(path: string): T {
	return JSON.parse(readFileSync(path, 'utf8')) as T;
}

export function fixtureNames(): string[] {
	return readdirSync(FIXTURES)
		.filter((n) => existsSync(join(FIXTURES, n, 'survey.json')))
		.sort();
}

export function casesOf(fixture: string): Case[] {
	const dir = join(FIXTURES, fixture, 'scripts');
	return readdirSync(dir)
		.filter((f) => f.endsWith('.json'))
		.sort()
		.map((file) => ({
			fixture,
			file,
			script: json<Script>(join(dir, file)),
			expected: json<Expected>(join(FIXTURES, fixture, 'expected', file))
		}));
}

/**
 * `OSP_HARNESS_FIXTURES`: comma-separated fixture folder names or number prefixes ("06,25").
 * Empty or unset: every fixture.
 */
export function selectFixtures(spec = process.env.OSP_HARNESS_FIXTURES ?? ''): string[] {
	const all = fixtureNames();
	const wanted = spec
		.split(',')
		.map((s) => s.trim())
		.filter(Boolean);
	if (!wanted.length) return all;
	const picked = all.filter((name) => wanted.some((w) => name === w || name.startsWith(`${w}-`)));
	// Only deleted fixtures were named (or none matched): run them all rather than nothing.
	return picked.length ? picked : all;
}

/** The variant key the launcher publishes a survey under (web/harness/server.py variant_key). */
export function variantKey(quotas: Record<string, string> | undefined): string {
	const q = quotas ?? {};
	const sorted: Record<string, string> = {};
	for (const k of Object.keys(q).sort()) sorted[k] = q[k]!;
	return JSON.stringify(sorted);
}
