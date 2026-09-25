import { api } from "../../lib/axios";

/**
 * One-time ops — its own thin API layer over the SAME Campaign Manager endpoints the
 * Automations page uses. Deliberately not imported from features/automations: a feature
 * never reaches into another, so one page's changes can never break the other.
 */
// The marketplace is part of every campaign-manager address, with no default on the
// server (ZC-D1) — and none here: every call takes `mp`, the navbar's one-marketplace
// choice for this page (`useAutomationMarketplace`).
const cm = (clientId, mp) => `/clients/${clientId}/campaign-manager/${mp}`;

/**
 * Every campaign on the account, not just the recent ones.
 *
 * ⚠️ `recent_only: false`, unlike the automation pickers. Those hide dead pre-migration
 * campaigns because you should not be able to SCHEDULE against one. Here the question is
 * the opposite — a stopped campaign is exactly what someone came to start — so the list
 * has to show everything and let status say what state each is in.
 */
export const getCampaigns = (clientId, mp, { days = 30 } = {}) =>
	api.get(`/clients/${clientId}/ads/campaigns`, {
		params: {
			// Only this marketplace's campaigns: the list merges marketplaces server-side,
			// and an action on the other one's id would be refused (a different namespace).
			marketplaces: mp,
			days,
			limit: 500,
			sort: "spend",
			order: "desc",
			recent_only: false,
		},
	});

// Pushes a budget to one campaign immediately. Enqueues a VM job, returns `{job_id}`.
export const setBudgetNow = (clientId, mp, campaignId, budget) =>
	api.post(`${cm(clientId, mp)}/set-budget`, {
		campaign_id: campaignId,
		budget,
	});

/**
 * Start or stop one campaign now. `budget` applies to "running" only: Blinkit's restart
 * re-submits the campaign and sets its budget, so a resume always carries one. Omitted,
 * the VM resolves it from a fresh read rather than guessing here.
 */
export const setActivationNow = (clientId, mp, campaignId, status, budget) =>
	api.post(`${cm(clientId, mp)}/campaigns/${campaignId}/activation`, {
		status,
		...(budget == null ? {} : { budget }),
	});

// Re-reads the account's campaigns and statuses from the marketplace into the catalogue.
// A read-only job, and the only way a campaign created today becomes visible here.
export const refreshCampaigns = (clientId, mp) =>
	api.post(`${cm(clientId, mp)}/campaigns/refresh`);

/**
 * One campaign's targets, for the detail drawer.
 *
 * ⚠️ `/ads/keywords?campaign_id=`, not `/ads/campaigns/{id}/keywords` — that path 404s.
 * Roughly 5s for a campaign's 60-odd rows, so it is fetched only when a drawer opens
 * rather than with the list.
 */
//
// ⚠️ Blinkit only — `/ads/keywords` is Blinkit's per-campaign keyword performance. Zepto
// has none (brand-grain keyword metrics), so its drawer lists the catalogue instead
// (`getCatalogKeywords`).
export const getCampaignTargets = (clientId, campaignId, { days = 30 } = {}) =>
	api.get(`/clients/${clientId}/ads/keywords`, {
		params: {
			marketplaces: "blinkit",
			campaign_id: campaignId,
			days,
			limit: 100,
			sort: "spend",
			order: "desc",
		},
	});

/**
 * The engine's own verdict on what it last did to a campaign.
 *
 * ⚠️ A finished job is not a finished WRITE. `status: success` means the job ran, not
 * that anything changed: the engine records `apply` or `skip` in its run log, and a
 * refused write still exits cleanly. `include_unchanged` is required — a skip is
 * exactly the "nothing changed" row the default view hides.
 */
/**
 * Every keyword a marketplace's campaign catalogue holds, with the live bid and floor. The
 * drawer's target list where there is no per-campaign keyword performance (Zepto).
 */
export const getCatalogKeywords = (clientId, mp) =>
	api.get(`${cm(clientId, mp)}/keywords`);

export const getLastVerdict = (clientId, mp, campaignId) =>
	api.get(`${cm(clientId, mp)}/history`, {
		params: { campaign_id: campaignId, limit: 1, include_unchanged: true },
	});

export const getJob = (clientId, mp, jobId) =>
	api.get(`${cm(clientId, mp)}/jobs/${jobId}`);
