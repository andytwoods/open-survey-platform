import { describe, expect, it } from 'vitest';
import { appTitle } from './index';

describe('builder scaffold', () => {
	it('has a title', () => {
		expect(appTitle).toBe('Open Survey Platform');
	});
});
