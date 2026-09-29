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
 * Campaign actions, reached through the Campaign Manager endpoints the Automations page
 * uses. Declared here rather than imported from that feature: an endpoint is a contract we
 * may both call, whereas another feature's internals are not ours to depend on.
 *
 * Both ENQUEUE a job and return its id; nothing has happened when the promise resolves.
 */
// The marketplace is part of every campaign-manager address, with no default on the
// server (ZC-D1) — and none here. This page can show several marketplaces at once, so an
// action names the ROW's marketplace (`CampaignRow.platform`); without one it throws
// rather than guessing, because a guess is how a Zepto id once reached Blinkit's account.
const cm = (clientId, marketplace) => {
	if (!marketplace)
		throw new Error(
			"No marketplace on this campaign row, so the action was not sent.",
		);
	return `/clients/${clientId}/campaign-manager/${marketplace}`;
};

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

export const setCampaignActivation = (
	clientId,
	marketplace,
	campaignId,
	status,
) =>
	api.post(
		`${cm(clientId, marketplace)}/campaigns/${campaignId}/activation`,
		{
			status,
		},
	);

export const setCampaignBudget = (clientId, marketplace, campaignId, budget) =>
	api.post(`${cm(clientId, marketplace)}/set-budget`, {
		campaign_id: campaignId,
		budget,
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
