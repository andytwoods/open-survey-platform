// replay.mjs: replay every stored event log through the participant engine and compare
// the final state with the stored response.
//
// Part of an Open Survey Platform reproducibility package. MIT License, Copyright (c) 2026
// Open Survey Platform contributors: permission is granted, free of charge, to use, copy,
// modify, merge, publish, distribute, sublicense and/or sell copies, provided this notice
// is kept. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND (full text in
// LICENSE.md).
//
//   node replay/replay.mjs            (from the package root; Node 18+, no npm install)
//   node replay/replay.mjs --json     (a machine-readable report)
//   node replay/replay.mjs --plan p.json --responses r.json
//
// engine.js is the exact engine bundle the platform served. For each response with an
// event log: replay(plan, events) must reproduce every recorded step, and result() must
// give the stored seed, end, conditions, realised orders and answers ({state, value}).
// Exit code: 0 all match, 1 at least one mismatch, 2 the inputs can't be read.

import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { canonicalJson, isState, planChecksum, replay, result } from './engine.js';

const here = (p) => fileURLToPath(new URL(p, import.meta.url));

function args(argv) {
	const out = { plan: here('../survey/plan.json'), responses: here('../data/responses.json'), json: false };
	for (let i = 0; i < argv.length; i++) {
		if (argv[i] === '--json') out.json = true;
		else if (argv[i] === '--plan') out.plan = argv[++i];
		else if (argv[i] === '--responses') out.responses = argv[++i];
	}
	return out;
}

function load(path, what) {
	try {
		return JSON.parse(readFileSync(path, 'utf8'));
	} catch (e) {
		throw new Error(`can't read ${what} (${path}): ${e.message}`);
	}
}

const same = (a, b) => canonicalJson(a ?? null) === canonicalJson(b ?? null);

function checkResponse(plan, r) {
	const out = { responseId: r.responseId, status: 'match', checks: 0, mismatches: [], notes: [] };
	const events = Array.isArray(r.events) ? r.events : [];
	if (events.length === 0) {
		out.status = 'skipped';
		out.notes.push('no event log stored');
		return out;
	}
	const state = replay(plan, events);
	if (!isState(state)) {
		out.status = 'mismatch';
		out.mismatches.push({ what: 'replay', stored: null, expected: state.error });
		return out;
	}
	const rec = result(state);
	const compare = (what, stored, expected) => {
		out.checks++;
		if (!same(stored, expected)) out.mismatches.push({ what, stored: stored ?? null, expected: expected ?? null });
	};
	compare('seed', r.seed, rec.sessionSeed);
	compare('end', r.end, rec.end);
	if (r.planChecksum != null) compare('planChecksum', r.planChecksum, rec.planChecksum);
	for (const [id, v] of Object.entries(plan.variables)) {
		if (v.kind === 'assigned') compare(`conditions.${v.name}`, r.conditions?.[v.name], rec.conditions[id]);
	}
	for (const kind of ['blocks', 'items', 'choices']) {
		const stored = r.orders?.[kind] ?? {};
		const realised = {};
		for (const [id, order] of Object.entries(rec.orders[kind])) {
			realised[kind === 'choices' ? (plan.items[id]?.name ?? id) : id] = order;
		}
		const keys = new Set([...Object.keys(realised), ...Object.keys(stored).filter((k) => stored[k] != null)]);
		for (const key of [...keys].sort()) compare(`orders.${kind}.${key}`, stored[key], realised[key]);
	}
	for (const id of plan.questions) {
		const name = plan.items[id]?.name ?? id;
		const a = rec.answers[id] ?? { state: null, value: null };
		const expected = { state: a.state ?? null, value: a.state === 'answered' ? (a.value ?? null) : null };
		compare(`answers.${name}`, r.answers?.[name], expected);
	}
	if (out.mismatches.length) out.status = 'mismatch';
	return out;
}

function main() {
	const opts = args(process.argv.slice(2));
	let report;
	try {
		const plan = load(opts.plan, 'the plan');
		report = { plan: { checksum: plan.checksum, checksumOk: planChecksum(plan) === plan.checksum }, responses: [] };
		if (existsSync(opts.responses)) {
			const data = load(opts.responses, 'the responses');
			for (const r of data.responses ?? []) report.responses.push(checkResponse(plan, r));
		} else {
			report.note = 'no participant data in this package: nothing to replay';
		}
	} catch (e) {
		console.error(`replay.mjs: ${e.message}`);
		return 2;
	}
	const count = (s) => report.responses.filter((r) => r.status === s).length;
	report.summary = { match: count('match'), mismatch: count('mismatch'), skipped: count('skipped') };
	const failed = report.summary.mismatch > 0 || !report.plan.checksumOk;
	if (opts.json) {
		console.log(JSON.stringify(report, null, 2));
		return failed ? 1 : 0;
	}
	console.log(`plan ${report.plan.checksum}: checksum ${report.plan.checksumOk ? 'ok' : 'MISMATCH'}`);
	if (report.note) console.log(report.note);
	for (const r of report.responses) {
		console.log(`${r.responseId}: ${r.status === 'mismatch' ? 'MISMATCH' : r.status} (${r.checks} checks)`);
		for (const m of r.mismatches) {
			console.log(`  ${m.what}: stored ${JSON.stringify(m.stored)}, replayed ${JSON.stringify(m.expected)}`);
		}
		for (const n of r.notes) console.log(`  note: ${n}`);
	}
	const s = report.summary;
	console.log(`${s.match} match, ${s.mismatch} mismatch, ${s.skipped} skipped`);
	return failed ? 1 : 0;
}

process.exitCode = main();
