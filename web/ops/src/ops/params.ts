/** Params-schema building blocks shared by the area modules (pydantic `Params` models). */

import { S, type Field, type Schema } from '../pyd.ts';

export const JSON_DICT_TAG =
	'dict[str,json-or-python[json=any,python=tagged-union[list[...],dict[str,...],str,bool,int,float,none]]]';

export const str = S.str();
export const JsonDict = S.dict(S.str(), S.json);
/** `str | dict[str, JsonValue]`: a label, plain, rich or per language. */
export const Text = S.union(['str', S.str()], [JSON_DICT_TAG, JsonDict]);
/** `int | str`. */
export const ChoiceValue = S.union(['int', S.int()], ['str', S.str()]);
export const QuestionType = S.literal('integer', 'decimal', 'text', 'single', 'multi', 'date', 'matrix', 'slider', 'note');

export function req(name: string, schema: Schema): Field {
	return { name, schema };
}
/** `T | None = None`. */
export function opt(name: string, schema: Schema): Field {
	return { name, schema: S.nullable(schema), default: null };
}
export function def(name: string, schema: Schema, value: Field['default']): Field {
	return { name, schema, default: value };
}
export const flag = (name: string): Field => def(name, S.bool, false);
/** `index: int | None = Field(default=None, ge=0)`. */
export const Index = opt('index', S.int({ ge: 0 }));
export const params = S.model;
