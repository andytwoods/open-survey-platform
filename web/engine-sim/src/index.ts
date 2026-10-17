/**
 * @osp/engine-sim: simulator and path coverage for runtime plans (task M1). Pure: the
 * builder can run it in the browser; the server runs it through `src/cli.ts` (Node sidecar).
 */

export {
	DEFAULT_EXHAUSTIVE_LIMIT,
	MAX_PARTICIPANTS,
	SIM_FORMAT,
	SimError,
	reachedNodes,
	simulate,
	type AnswerStrategy,
	type PathSpace,
	type SimOptions,
	type SimResult,
	type StateCounts,
	type Stats
} from './simulate.ts';
export { BLANK, exhaustiveDomains, numericPoints, structure, usage, type Structure } from './structure.ts';
export { rng, type Rng } from './prng.ts';
export {
	FAKE_FORMAT,
	FakeParticipants,
	type Ask,
	type AskReply,
	type ParticipantOutcome,
	type ParticipantSpec
} from './fake.ts';
