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

/**
 * Every write from this page says it came from this page.
 *
 * The server cannot otherwise tell: Ad Automation calls these exact endpoints too, so the
 * job type alone says nothing about which page a click came from. This page's operations
 * list shows ONLY what was started here, and it filters on this value.
 */
export const ONE_TIME_OPS = "one-time-ops";
const fromHere = { params: { source: ONE_TIME_OPS } };

// Pushes a budget to one campaign immediately. Enqueues a VM job, returns `{job_id}`.
export const setBudgetNow = (clientId, campaignId, budget) =>
	api.post(
		`${cm(clientId)}/set-budget`,
		{ campaign_id: campaignId, budget },
		fromHere,
	);

/**
 * Start or stop one campaign now. `budget` applies to "running" only: Blinkit's restart
 * re-submits the campaign and sets its budget, so a resume always carries one. Omitted,
 * the VM resolves it from a fresh read rather than guessing here.
 */
export const setActivationNow = (clientId, campaignId, status, budget) =>
	api.post(
		`${cm(clientId)}/campaigns/${campaignId}/activation`,
		{ status, ...(budget == null ? {} : { budget }) },
		fromHere,
	);

// Re-reads the account's campaigns and statuses from Blinkit into the catalogue. A
// read-only job, and the only way a campaign created today becomes visible here.
export const refreshCampaigns = (clientId) =>
	api.post(`${cm(clientId)}/campaigns/refresh`, null, fromHere);

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

// Operation progress and outcomes: lib/actions.js, shared with Ad Automation. An outcome is
// read by the operation's own `run_id` — the lookup this replaced read "the newest row for
// this campaign", which picked up another engine's row whenever one ran on the same
// campaign in the same minute (the `cm_bid` and `cm_ops` lanes run in parallel).
