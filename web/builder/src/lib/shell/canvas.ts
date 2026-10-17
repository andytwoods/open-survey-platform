/**
 * What the canvas feeds the question cards (lib/cards): each question's own JSON from the
 * survey document, by id, and its property schema in the cards' shape. Display only; a
 * malformed document gives fewer entries, never an exception.
 */
import type { CardQuestion, PropertySchemaData } from '../cards/types';
import type { TypeSchema } from '../properties/types';

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v);
const list = (v: unknown): Obj[] => (Array.isArray(v) ? v.filter(isObj) : []);

/** Question id → the question object, for every question with a string id and type. */
export function canvasQuestions(survey: unknown): Map<string, CardQuestion> {
	const out = new Map<string, CardQuestion>();
	if (!isObj(survey)) return out;
	for (const b of list(survey.blocks)) {
		for (const p of list(b.pages)) {
			for (const q of list(p.items)) {
				if (typeof q.id === 'string' && typeof q.type === 'string' && !out.has(q.id)) {
					out.set(q.id, q as CardQuestion);
				}
			}
		}
	}
	return out;
}

/** A question type's schema as the cards read it (same JSON; null when there is none). */
export function cardSchema(schema: TypeSchema | undefined | null): PropertySchemaData | null {
	return schema ? (schema as unknown as PropertySchemaData) : null;
}
