/**
 * Survey-level ops: consent, endings, redirect templates, hooks, theme (ports of
 * `consent_ops`, `ending_ops`, `redirect_ops`, `hooks_ops`, `theme_ops`) and the
 * whole-document ops `replace_survey` and `apply_patch` (`survey_ops`).
 */

import { setKey } from '../doc.ts';
import { Ending, Hooks, Name, OutcomeKey, RedirectTemplate, Theme } from '../models.ts';
import * as jp from '../patch.ts';
import { dump, validate, type PydError } from '../pyd.ts';
import { deepCopy, get as dget, has, isObj, slice, type Json, type JsonObject } from '../py.ts';
import { REVERSE_PATCH, OpError, op, type Invocation } from '../registry.ts';
import { normaliseText } from '../spec.ts';
import { JsonDict, opt, params, req } from './params.ts';
import { S } from '../pyd.ts';

function pointerOf(loc: (string | number)[], keep: (p: string | number) => boolean = () => true): string {
	return loc
		.filter(keep)
		.map((x) => '/' + String(x).replaceAll('~', '~0').replaceAll('/', '~1'))
		.join('');
}

// --- consent ------------------------------------------------------------------------------------

const SetConsent = params('SetConsent', [opt('consent', JsonDict)]);

op('set_consent', SetConsent, { label: 'Set consent page', area: 'survey' }, (ctx, p): Invocation => {
	if (p.consent === null) delete ctx.d.consent;
	else {
		const consent = deepCopy(p.consent as JsonObject);
		for (const key of ['text', 'agreeLabel', 'declineLabel']) if (has(consent, key)) consent[key] = normaliseText(consent[key]!);
		ctx.d.consent = consent;
	}
	ctx.touch();
	return REVERSE_PATCH;
});

// --- endings ------------------------------------------------------------------------------------

const SetEnding = params('SetEnding', [req('outcome', OutcomeKey), opt('ending', JsonDict)]);

op('set_ending', SetEnding, { label: 'Set ending', area: 'survey' }, (ctx, p): Invocation => {
	const settings0 = dget(ctx.d, 'settings');
	const endings0 = isObj(settings0) ? dget(settings0, 'endings') : undefined;
	if (p.ending === null) {
		if (!isObj(settings0) || !isObj(endings0)) return REVERSE_PATCH;
		if (!has(endings0, p.outcome)) return REVERSE_PATCH;
		delete endings0[p.outcome];
		if (Object.keys(endings0).length === 0) delete settings0.endings;
		return REVERSE_PATCH;
	}
	const raw: JsonObject = { ...(p.ending as JsonObject) };
	for (const key of ['title', 'body']) if (has(raw, key)) raw[key] = normaliseText(raw[key]!);
	const redirect = dget(raw, 'redirect');
	if (isObj(redirect) && has(redirect, 'label')) raw.redirect = { ...redirect, label: normaliseText(redirect.label!) };
	const r = validate(Ending, raw);
	if (!r.ok) {
		const e = r.errs[0]!;
		throw new OpError(
			'op.invalid_result',
			slice(`not a valid ending: ${e.msg}`, 0, 300),
			`/settings/endings/${p.outcome}${pointerOf(e.loc)}`
		);
	}
	let settings = settings0;
	if (!isObj(settings)) settings = ctx.d.settings = {};
	let endings = isObj(settings) ? dget(settings, 'endings') : undefined;
	if (!isObj(endings)) endings = (settings as JsonObject).endings = {};
	setKey(endings as JsonObject, p.outcome, dump(r.v, { excludeUnset: true }));
	return REVERSE_PATCH;
});

// --- redirect templates ---------------------------------------------------------------------------

const SetRedirectTemplate = params('SetRedirectTemplate', [req('name', Name), opt('template', JsonDict)]);

op('set_redirect_template', SetRedirectTemplate, { label: 'Set redirect template', area: 'survey' }, (ctx, p): Invocation => {
	const settings0 = dget(ctx.d, 'settings');
	const templates0 = isObj(settings0) ? dget(settings0, 'redirectTemplates') : undefined;
	if (p.template === null) {
		if (!isObj(settings0) || !isObj(templates0)) return REVERSE_PATCH;
		if (!has(templates0, p.name)) return REVERSE_PATCH;
		delete templates0[p.name];
		if (Object.keys(templates0).length === 0) delete settings0.redirectTemplates;
		return REVERSE_PATCH;
	}
	const r = validate(RedirectTemplate, p.template);
	if (!r.ok) {
		const e = r.errs[0]!;
		throw new OpError(
			'op.invalid_result',
			slice(`not a valid redirect template: ${e.msg}`, 0, 300),
			`/settings/redirectTemplates/${p.name}${pointerOf(e.loc)}`
		);
	}
	let settings = settings0;
	if (!isObj(settings)) settings = ctx.d.settings = {};
	let templates = dget(settings as JsonObject, 'redirectTemplates');
	if (!isObj(templates)) templates = (settings as JsonObject).redirectTemplates = {};
	setKey(templates as JsonObject, p.name, dump(r.v, { excludeNone: true }));
	return REVERSE_PATCH;
});

// --- hooks --------------------------------------------------------------------------------------

const SetHooks = params('SetHooks', [opt('hooks', JsonDict)]);

function firstProblem(errs: PydError[]): [string, string] {
	const e = errs[0]!;
	return [pointerOf(e.loc, (x) => !String(x).startsWith('[')), e.msg];
}

op('set_hooks', SetHooks, { label: 'Set researcher hooks', area: 'survey' }, (ctx, p): Invocation => {
	if (p.hooks === null) {
		if (!has(ctx.d, 'hooks')) return REVERSE_PATCH;
		delete ctx.d.hooks;
		ctx.touch();
		return REVERSE_PATCH;
	}
	const r = validate(Hooks, p.hooks);
	if (!r.ok) {
		const [ptr, msg] = firstProblem(r.errs);
		throw new OpError('op.invalid_result', slice(`not a valid hook manifest: ${msg}`, 0, 300), '/hooks' + ptr);
	}
	ctx.d.hooks = dump(r.v, { excludeNone: true });
	ctx.touch();
	return REVERSE_PATCH;
});

// --- theme --------------------------------------------------------------------------------------

const SetTheme = params('SetTheme', [opt('theme', JsonDict)]);

op('set_theme', SetTheme, { label: 'Set survey theme', area: 'survey' }, (ctx, p): Invocation => {
	const settings0 = dget(ctx.d, 'settings');
	if (p.theme === null) {
		if (!isObj(settings0) || !has(settings0, 'theme')) return REVERSE_PATCH;
		delete settings0.theme;
		if (Object.keys(settings0).length === 0) delete ctx.d.settings;
		ctx.touch();
		return REVERSE_PATCH;
	}
	const r = validate(Theme, p.theme);
	if (!r.ok) {
		const first = r.errs[0];
		throw new OpError(
			'op.invalid_result',
			slice(`not a valid theme: ${first ? first.msg : 'schema mismatch'}`, 0, 300),
			'/settings/theme' + (first ? pointerOf(first.loc) : '')
		);
	}
	let settings = settings0;
	if (!isObj(settings)) settings = ctx.d.settings = {};
	(settings as JsonObject).theme = dump(r.v);
	ctx.touch();
	return REVERSE_PATCH;
});

// --- whole document -------------------------------------------------------------------------------

const ReplaceSurvey = params('ReplaceSurvey', [req('survey', JsonDict)]);

op(
	'replace_survey',
	ReplaceSurvey,
	{ label: 'Replace survey (JSON)', area: 'survey', wholeDocument: true },
	(ctx, p): Invocation => {
		ctx.doc = deepCopy(p.survey as JsonObject);
		ctx.touch();
		return { op: 'replace_survey', params: { survey: deepCopy(ctx.before) } };
	}
);

const ApplyPatch = params('ApplyPatch', [req('patch', S.list(JsonDict))]);

op('apply_patch', ApplyPatch, { label: 'Apply JSON Patch', area: 'survey', wholeDocument: true }, (ctx, p): Invocation => {
	try {
		ctx.doc = jp.apply(ctx.doc, (p.patch as Json[]).map((o) => ({ ...(o as JsonObject) })));
	} catch (e) {
		if (e instanceof jp.PatchError) throw new OpError('op.patch', slice(e.message, 0, 300));
		throw e;
	}
	ctx.touch();
	return REVERSE_PATCH;
});
