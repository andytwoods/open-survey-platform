import { describe, expect, it } from 'vitest';
import { CommandRegistry } from '../commands/registry';
import { appearanceCommands, type BuilderView } from './commands';

describe('appearance commands', () => {
	it('switch views through the registry, each enabled only where it makes sense', () => {
		let view: BuilderView = 'editor';
		const registry = new CommandRegistry();
		registry.registerAll(appearanceCommands({ view: () => view, open: (v) => (view = v) }));
		expect(registry.isEnabled('view.editor')).toBe(false);
		expect(registry.run('view.appearance')).toBe(true);
		expect(view).toBe('appearance');
		expect(registry.run('view.appearance')).toBe(false);
		expect(registry.run('view.editor')).toBe(true);
		expect(view).toBe('editor');
	});
});
