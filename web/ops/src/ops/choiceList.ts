/** Shared choice list ops: create, delete (port of `osp_ops.choice_list_ops`). */

import { CHOICE_LIST, claimId, deleteWithRefs, get, insertAt, locate } from '../doc.ts';
import { S } from '../pyd.ts';
import { deepCopy, has, type Json, type JsonObject } from '../py.ts';
import { REVERSE_PATCH, op, type Invocation } from '../registry.ts';
import { DEFAULT_CHOICES } from './question.ts';
import { Index, JsonDict, flag, opt, params, req, str } from './params.ts';

const CreateChoiceList = params('CreateChoiceList', [opt('id', str), opt('choices', S.list(JsonDict)), Index]);

op('create_choice_list', CreateChoiceList, { label: 'Create choice list', area: 'choiceLists' }, (ctx, p): Invocation => {
	const lid = claimId(ctx, p.id, 'list');
	const choices = deepCopy((p.choices ?? DEFAULT_CHOICES) as Json[]);
	if (!has(ctx.d, 'choiceLists')) ctx.d.choiceLists = [];
	insertAt(ctx.d.choiceLists as Json[], p.index, { id: lid, choices });
	ctx.touch();
	return { op: 'delete_choice_list', params: { id: lid, force: true } };
});

const DeleteChoiceList = params('DeleteChoiceList', [req('id', str), flag('cascade'), flag('force')]);

op('delete_choice_list', DeleteChoiceList, { label: 'Delete choice list', area: 'choiceLists' }, (ctx, p): Invocation => {
	const loc = locate(ctx, p.id, CHOICE_LIST);
	const choices = get(ctx.doc, loc.path).choices as Json[];
	const [cl, cascaded] = deleteWithRefs(ctx, loc, new Set([p.id]), {
		cascade: p.cascade,
		force: p.force,
		what: `choice list '${p.id}'`,
		inline: new Map([[p.id, choices]])
	});
	if (cascaded) return REVERSE_PATCH;
	const c = cl as JsonObject;
	return { op: 'create_choice_list', params: { id: c.id!, choices: c.choices!, index: loc.index } };
});
