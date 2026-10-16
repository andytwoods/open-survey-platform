/**
 * MOCK DATA, NOT A SURVEY MODEL.
 *
 * A static, survey-shaped tree so the W1 shell has something real-looking to show
 * (pages → blocks → questions). It is not `osp-spec`, carries no survey semantics and
 * must not grow any. The real builder renders the store fed by the op client (B2); this
 * stays for component tests behind the `?mock` flag.
 * Content is invented; no real personal data.
 */
import type { NodeType, OutlineNode } from '../model/outline';

// Same shape the real survey is projected into (model/outline.ts). Shown at `/?mock`.
export type MockNodeType = NodeType;
export type MockNode = OutlineNode;

const q = (id: string, label: string, family: MockNode['family']): MockNode => ({
	id,
	type: 'question',
	label,
	family
});

export const MOCK_SURVEY: MockNode = {
	id: 'survey_mock',
	type: 'survey',
	label: 'Sleep and study habits (mock)',
	children: [
		{
			id: 'p_welcome',
			type: 'page',
			label: 'Welcome',
			children: [
				{
					id: 'b_intro',
					type: 'block',
					label: 'Introduction',
					children: [
						q('q_info', 'About this study', 'note'),
						q('q_consent', 'I agree to take part', 'choice')
					]
				}
			]
		},
		{
			id: 'p_habits',
			type: 'page',
			label: 'Habits',
			children: [
				{
					id: 'b_sleep',
					type: 'block',
					label: 'Sleep',
					children: [
						q('q_hours', 'Hours of sleep on a typical night', 'number'),
						q('q_quality', 'How would you rate your sleep quality?', 'scale'),
						q('q_devices', 'Devices used in bed', 'choice')
					]
				},
				{
					id: 'b_study',
					type: 'block',
					label: 'Study',
					children: [
						q('q_study_grid', 'How often do you study at these times?', 'matrix'),
						q('q_study_place', 'Where do you usually study?', 'text')
					]
				}
			]
		},
		{
			id: 'p_end',
			type: 'page',
			label: 'Finish',
			children: [
				{
					id: 'b_end',
					type: 'block',
					label: 'Wrap-up',
					children: [q('q_comments', 'Anything else you would like to tell us?', 'text')]
				}
			]
		}
	]
};
