import { describe, expect, it } from 'vitest';
import { EDGE, edgeSpeed, MAX_SPEED } from './auto-scroll';

// Auto-scroll while dragging on the canvas (B19): the speed for a pointer near an edge.

describe('edgeSpeed', () => {
	it('is zero away from the edges', () => {
		expect(edgeSpeed(300, 0, 600)).toBe(0);
		expect(edgeSpeed(EDGE, 0, 600)).toBe(0);
		expect(edgeSpeed(600 - EDGE, 0, 600)).toBe(0);
	});

	it('scrolls up near the top and down near the bottom, faster closer in', () => {
		expect(edgeSpeed(EDGE - 10, 0, 600)).toBeLessThan(0);
		expect(edgeSpeed(600 - EDGE + 10, 0, 600)).toBeGreaterThan(0);
		expect(Math.abs(edgeSpeed(2, 0, 600))).toBeGreaterThan(Math.abs(edgeSpeed(EDGE - 10, 0, 600)));
	});

	it('is capped, also with the pointer past the edge', () => {
		expect(edgeSpeed(-100, 0, 600)).toBe(-MAX_SPEED);
		expect(edgeSpeed(900, 0, 600)).toBe(MAX_SPEED);
	});

	it('does nothing for a scroller too short to have two edges, or a bad pointer', () => {
		expect(edgeSpeed(10, 0, EDGE)).toBe(0);
		expect(edgeSpeed(Number.NaN, 0, 600)).toBe(0);
	});
});
