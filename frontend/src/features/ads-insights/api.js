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
 * The keyword table's rows: every campaign × keyword × match type of every marketplace in
 * scope, plus what period each marketplace's rows cover — Blinkit's are an 8-day snapshot
 * ending on or before `end`, never the picker's window. One request, not paginated: the
 * table groups by keyword in the browser.
 */
export const getKeywordInsights = (clientId, { start, end, marketplaces }) =>
	api.get(`/clients/${clientId}/ads/keyword-insights`, {
		params: {
			start,
			end,
			marketplaces: marketplaces?.length
				? marketplaces.join(",")
				: undefined,
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

/**
 * Ad spend and return per product, retail category or city (`dimension`), across the
 * marketplaces in scope that report it — Zepto today; Blinkit reports none. `adType` is
 * Zepto's ad type and narrows Zepto's rows.
 */
export const getBreakdowns = (
	clientId,
	{ start, end, marketplaces, dimension, adType },
) =>
	api.get(`/clients/${clientId}/ads/breakdowns`, {
		params: {
			start,
			end,
			dimension,
			ad_type: adType || undefined,
			marketplaces: marketplaces?.length
				? marketplaces.join(",")
				: undefined,
		},
	});
