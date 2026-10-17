/**
 * The results API's shapes (task V1, `contract/openapi.json`), named for the results page.
 * Generated types only: nothing here is hand-written data.
 */
import type { components } from '@osp/api-client';

type S = components['schemas'];

export type ResultsQuery = S['ResultsQuery'];
export type ResultsResponse = S['ResultsResponse'];
export type Card = S['Card'];
export type CardType = Card['type'];
export type Facet = S['Facet'];
export type Group = S['Group'];
export type Cell = S['Cell'];
export type Category = S['Category'];
export type RowResult = S['RowResult'];
export type Stats = S['Stats'];
export type StateCounts = S['StateCounts'];
export type ResultWarning = S['ResultWarning'];
export type CardRequest = S['CardRequest'];
export type TextPage = S['TextPage'];
export type TextItem = S['TextItem'];
export type SplitInfo = S['SplitInfo'];

/** What one table or chart shows: a card, one version facet of it, or one matrix row. */
export interface ResultUnit {
	groups: Group[];
	categories?: Category[] | null;
	binning?: Card['binning'];
	binEdges?: number[] | null;
	binUnit?: Card['binUnit'];
}
