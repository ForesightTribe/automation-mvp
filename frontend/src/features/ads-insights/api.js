/**
 * Insights: API surface.
 *
 * One line, deliberately. Insights is a new VIEW over the same ads data, so it drives the
 * exact endpoints the Ads page does. Copying the wrappers would let the two drift; this
 * re-exports that module verbatim, and the Ads feature is never modified.
 *
 * If Insights ever needs a call the Ads page does not make, add it here alongside the
 * re-export rather than editing the Ads feature.
 */
export * from "../ads/api";

import { api } from "../../lib/axios";

/**
 * One page of keyword rows for CURRENT campaigns only (`recent_only`).
 *
 * The keyword table groups every row by search term in the browser, so it needs them all,
 * not a page of twenty. `recent_only` leaves out the pre-migration account's campaigns:
 * their "latest" snapshot is from July, so their numbers are not in any window the date
 * picker can select, and they mostly share names with their replacements.
 */
export const getKeywordRowsPage = (clientId, { marketplaces, page, limit }) =>
	api.get(`/clients/${clientId}/ads/keywords`, {
		params: {
			marketplaces: marketplaces?.length
				? marketplaces.join(",")
				: undefined,
			target_type: "keyword",
			recent_only: true,
			sort: "spend",
			order: "desc",
			page,
			limit,
		},
	});

/**
 * Every campaign's spend per day over [start, end], for the days it spent — the
 * budget-utilisation views' data in ONE request. They used to call `/ads/campaigns` once
 * per day (up to 31), each holding a pooled API connection (2026-09-25).
 */
export const getCampaignsDaily = (clientId, { start, end, marketplaces }) =>
	api.get(`/clients/${clientId}/ads/campaigns/daily`, {
		params: {
			start,
			end,
			marketplaces: marketplaces?.length
				? marketplaces.join(",")
				: undefined,
		},
	});
