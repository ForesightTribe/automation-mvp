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
const cm = (clientId) => `/clients/${clientId}/campaign-manager`;

export const setCampaignActivation = (clientId, campaignId, status) =>
	api.post(`${cm(clientId)}/campaigns/${campaignId}/activation`, { status });

export const setCampaignBudget = (clientId, campaignId, budget) =>
	api.post(`${cm(clientId)}/set-budget`, { campaign_id: campaignId, budget });
