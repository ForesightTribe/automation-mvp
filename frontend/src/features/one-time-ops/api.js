import { api } from "../../lib/axios";

/**
 * One-time ops — its own thin API layer over the SAME Campaign Manager endpoints the
 * Automations page uses. Deliberately not imported from features/automations: a feature
 * never reaches into another, so one page's changes can never break the other.
 *
 * No backend changes. Every call here already existed and is already used elsewhere.
 */
const cm = (clientId) => `/clients/${clientId}/campaign-manager`;

/**
 * Every campaign on the account, not just the recent ones.
 *
 * ⚠️ `recent_only: false`, unlike the automation pickers. Those hide dead pre-migration
 * campaigns because you should not be able to SCHEDULE against one. Here the question is
 * the opposite — a stopped campaign is exactly what someone came to start — so the list
 * has to show everything and let status say what state each is in.
 */
export const getCampaigns = (clientId, { days = 30 } = {}) =>
	api.get(`/clients/${clientId}/ads/campaigns`, {
		params: {
			days,
			limit: 500,
			sort: "spend",
			order: "desc",
			recent_only: false,
		},
	});

// Pushes a budget to one campaign immediately. Enqueues a VM job, returns `{job_id}`.
export const setBudgetNow = (clientId, campaignId, budget) =>
	api.post(`${cm(clientId)}/set-budget`, {
		campaign_id: campaignId,
		budget,
	});

/**
 * Start or stop one campaign now. `budget` applies to "running" only: Blinkit's restart
 * re-submits the campaign and sets its budget, so a resume always carries one. Omitted,
 * the VM resolves it from a fresh read rather than guessing here.
 */
export const setActivationNow = (clientId, campaignId, status, budget) =>
	api.post(`${cm(clientId)}/campaigns/${campaignId}/activation`, {
		status,
		...(budget == null ? {} : { budget }),
	});

// Re-reads the account's campaigns and statuses from Blinkit into the catalogue. A
// read-only job, and the only way a campaign created today becomes visible here.
export const refreshCampaigns = (clientId) =>
	api.post(`${cm(clientId)}/campaigns/refresh`);

/**
 * One campaign's targets, for the detail drawer.
 *
 * ⚠️ `/ads/keywords?campaign_id=`, not `/ads/campaigns/{id}/keywords` — that path 404s.
 * Roughly 5s for a campaign's 60-odd rows, so it is fetched only when a drawer opens
 * rather than with the list.
 */
export const getCampaignTargets = (clientId, campaignId, { days = 30 } = {}) =>
	api.get(`/clients/${clientId}/ads/keywords`, {
		params: {
			campaign_id: campaignId,
			days,
			limit: 100,
			sort: "spend",
			order: "desc",
		},
	});

export const getJob = (clientId, jobId) =>
	api.get(`${cm(clientId)}/jobs/${jobId}`);
