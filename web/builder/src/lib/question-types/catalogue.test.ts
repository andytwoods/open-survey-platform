import { describe, expect, it } from 'vitest';
import { shellCommands, type ShellActions } from '../shell/commands';
import {
	LAST_TYPE_KEY,
	QUESTION_TYPES,
	filterTypes,
	isQuestionType,
	lastUsedType,
	orderTypes,
	questionTypeInfo,
	rememberType
} from './catalogue';

const ids = (ts: readonly { id: string }[]) => ts.map((t) => t.id);

describe('question type catalogue', () => {
	it('lists the nine osp-ops question types, each with a name, description and icon', () => {
		expect(ids(QUESTION_TYPES)).toEqual(['text', 'integer', 'decimal', 'single', 'multi', 'date', 'matrix', 'slider', 'note']);
		for (const t of QUESTION_TYPES) {
			expect(t.name).toBeTruthy();
			expect(t.description.length).toBeGreaterThan(10);
			expect(t.icon).toBeTruthy();
		}
		expect(questionTypeInfo('matrix')?.name).toBe('Grid');
		expect(questionTypeInfo('essay')).toBeUndefined();
		expect(isQuestionType('note')).toBe(true);
		expect(isQuestionType('__proto__')).toBe(false);
	});

	it('puts the last used type first, keeping the rest in order', () => {
		expect(ids(orderTypes('slider')).slice(0, 3)).toEqual(['slider', 'text', 'integer']);
		expect(ids(orderTypes(null))).toEqual(ids(QUESTION_TYPES));
		expect(orderTypes('slider')).toHaveLength(9);
	});

	it('filters by name, id and keywords, names first', () => {
		expect(ids(filterTypes(QUESTION_TYPES, 'single'))).toEqual(['single']);
		expect(ids(filterTypes(QUESTION_TYPES, 'checkbox'))).toEqual(['multi']);
		expect(ids(filterTypes(QUESTION_TYPES, 'MATRIX'))).toEqual(['matrix']);
		expect(ids(filterTypes(QUESTION_TYPES, 'number'))).toEqual(['integer', 'decimal']);
		expect(ids(filterTypes(QUESTION_TYPES, 'choice'))).toEqual(['single', 'multi']);
		expect(ids(filterTypes(QUESTION_TYPES, '  '))).toEqual(ids(QUESTION_TYPES));
		expect(filterTypes(QUESTION_TYPES, 'zzz')).toEqual([]);
		// Every word must match.
		expect(ids(filterTypes(QUESTION_TYPES, 'whole num'))).toEqual(['integer']);
	});
});

describe('last used type', () => {
	const memory = () => {
		const m = new Map<string, string>();
		return {
			getItem: (k: string) => m.get(k) ?? null,
			setItem: (k: string, v: string) => void m.set(k, v),
			m
		};
	};

	it('round-trips through storage under its own key', () => {
		const s = memory();
		expect(lastUsedType(s)).toBeNull();
		rememberType('multi', s);
		expect(s.m.get(LAST_TYPE_KEY)).toBe('multi');
		expect(lastUsedType(s)).toBe('multi');
	});

	it('ignores junk and survives storage that throws or is missing', () => {
		const s = memory();
		s.setItem(LAST_TYPE_KEY, 'essay');
		expect(lastUsedType(s)).toBeNull();
		const broken = {
			getItem: () => {
				throw new Error('SecurityError');
			},
			setItem: () => {
				throw new Error('QuotaExceeded');
			}
		};
		expect(lastUsedType(broken)).toBeNull();
		expect(() => rememberType('text', broken)).not.toThrow();
		expect(lastUsedType(undefined)).toBeNull();
	});
});

describe('palette commands for types', () => {
	const noop = () => {};
	const calls: string[] = [];
	const actions: ShellActions = {
		togglePalette: noop,
		undo: noop,
		redo: noop,
		cyclePane: noop,
		toggleTheme: noop,
		systemTheme: noop,
		toggleOutline: noop,
		toggleProperties: noop,
		outlineCollapsible: () => false,
		propertiesCollapsible: () => false,
		preview: noop,
		clearSelection: noop,
		addQuestion: () => calls.push('picker'),
		addQuestionOfType: (t) => calls.push(t),
		changeQuestionType: () => calls.push('change'),
		canChangeType: () => true,
		canEdit: () => true
	};

	it('has one "Add … question" per type, the picker, and "Change question type"', () => {
		const cmds = shellCommands(actions);
		const labels = cmds.map((c) => c.label);
		expect(labels).toContain('Add question…');
		expect(labels).toContain('Add single choice question');
		expect(labels).toContain('Add whole number question');
		expect(labels).toContain('Add grid question');
		expect(labels).toContain('Add note');
		expect(labels).toContain('Change question type…');
		expect(cmds.filter((c) => c.id.startsWith('survey.addQuestion.'))).toHaveLength(9);
		cmds.find((c) => c.id === 'survey.addQuestion.slider')!.run();
		cmds.find((c) => c.id === 'survey.addQuestion')!.run();
		cmds.find((c) => c.id === 'question.changeType')!.run();
		expect(calls).toEqual(['slider', 'picker', 'change']);
	});
});
