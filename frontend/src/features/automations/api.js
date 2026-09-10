import { api } from "../../lib/axios";

/**
 * Automations — an independent view over the SAME Campaign Manager backend
 * (/clients/{clientId}/campaign-manager, plus the Ads campaign/keyword
 * catalogue). Deliberately NOT imported from features/campaign-manager/api.js:
 * this feature owns its own thin API layer, the same way zepto_ads.py stays a
 * separate module from ads.py so one page's changes can never affect the
 * other. No backend changes — every call below hits an endpoint that already
 * exists and is already used by the Campaign Manager page.
 */
const base = (clientId) => `/clients/${clientId}/campaign-manager`;

// ── Reads ────────────────────────────────────────────────────────────────────
export const getBudgetSchedules = (clientId) =>
	api.get(`${base(clientId)}/budget-schedules`);

export const getBidRules = (clientId) => api.get(`${base(clientId)}/bid-rules`);

export const getHistory = (clientId, { page = 1, limit = 20, kind } = {}) =>
	api.get(`${base(clientId)}/history`, { params: { page, limit, kind } });

export const getJob = (clientId, jobId) =>
	api.get(`${base(clientId)}/jobs/${jobId}`);

export const getAdvertiser = (clientId) =>
	api.get(`${base(clientId)}/advertiser`);

// The Blinkit advertiser account every write goes through. Read + write, because the
// engine cannot act at all until one is bound.
export const setAdvertiser = (clientId, advertiserId) =>
	api.put(`${base(clientId)}/advertiser`, { advertiser_id: advertiserId });

// Blinkit's published bid range per keyword + the campaign's city targeting, from the
// daily scrape (V7.4). Never 404s: an unscraped campaign returns empty fields, so the
// form falls back to free text rather than blocking.
export const getBidContext = (clientId, campaignId) =>
	api.get(`${base(clientId)}/campaigns/${campaignId}/bid-context`);

// Reuses the Ads campaign catalogue, same as Campaign Manager's own picker —
// see that feature's api.js for why (recent_only excludes a stale pre-migration
// account's dead campaigns from being selectable).
export const getCampaigns = (clientId) =>
	api.get(`/clients/${clientId}/ads/campaigns`, {
		params: {
			days: 365,
			limit: 250,
			sort: "spend",
			order: "desc",
			recent_only: true,
		},
	});

export const getCampaignKeywords = (clientId, campaignId) =>
	api.get(`/clients/${clientId}/ads/campaigns/${campaignId}/keywords`);

// Per-keyword PERFORMANCE from the campaign-detail snapshots — impressions, spend, both
// ROAS figures, CPM, new users, and `most_viewed_position`, the rank the keyword actually
// holds today. Reads a different table from the (currently broken) endpoint above, so it
// is the source that reliably has both names and numbers. limit=250 because a campaign
// carries tens to low hundreds of keywords and the picker shows them all.
// Every keyword row the tenant has, across all campaigns — the two-pivot picker needs
// them all to group either way. Paged because the API caps a page at 500 and a tenant
// carries ~1.3k rows; three requests, then cached for the session.
// Names only, and deliberately WITHOUT recent_only: the keyword rows reference campaigns
// that the selectable list hides (dead pre-migration ones), and a row labelled
// "Campaign 362427" is worse than one labelled with the name it actually had.
// One campaign's performance over the window the user has actually selected, so the detail
// view agrees with the date picker in the navbar instead of quietly reporting a year.
export const getCampaignsForRange = (clientId, days) =>
	api.get(`/clients/${clientId}/ads/campaigns`, {
		params: {
			days,
			limit: 500,
			sort: "spend",
			order: "desc",
			recent_only: false,
		},
	});

export const getCampaignNames = (clientId) =>
	api.get(`/clients/${clientId}/ads/campaigns`, {
		params: {
			days: 365,
			limit: 500,
			sort: "spend",
			order: "desc",
			recent_only: false,
		},
	});

// ⚠️ This endpoint is SLOW — ~7-11s per page, because the service loads every detail row
// for the tenant and picks the latest snapshot in Python. A tenant has ~1.3k keyword rows
// over 3 pages, so fetching them one after another costs ~27s of blank screen.
//
// So it is split: page 1 alone (sorted by spend, i.e. the keywords anyone would actually
// automate), rendered as soon as it lands, and the remaining pages fetched IN PARALLEL and
// merged in afterwards. Same total data, roughly a third of the wait before something is
// on screen, and the tail arrives while the user is reading the top.
export const getKeywordMetricsPage = (clientId, page) =>
	api.get(`/clients/${clientId}/ads/keywords`, {
		params: {
			target_type: "keyword",
			sort: "spend",
			order: "desc",
			limit: 500,
			page,
		},
	});

export const getKeywordMetricsRest = async (clientId, pages) => {
	if (pages < 2) return [];
	const rest = await Promise.all(
		Array.from({ length: pages - 1 }, (_, i) =>
			getKeywordMetricsPage(clientId, i + 2),
		),
	);
	return rest.flatMap((r) => r.items ?? []);
};

export const getKeywordMetrics = (clientId, campaignId) =>
	api.get(`/clients/${clientId}/ads/keywords`, {
		params: {
			campaign_id: campaignId,
			target_type: "keyword",
			sort: "spend",
			order: "desc",
			limit: 250,
		},
	});

// ── Budget schedules + rules (campaign automations) ─────────────────────────
export const createBudgetSchedule = (clientId, body) =>
	api.post(`${base(clientId)}/budget-schedules`, body);

export const updateBudgetSchedule = (clientId, scheduleId, body) =>
	api.patch(`${base(clientId)}/budget-schedules/${scheduleId}`, body);

export const deleteBudgetSchedule = (clientId, scheduleId) =>
	api.delete(`${base(clientId)}/budget-schedules/${scheduleId}`);

export const addBudgetRule = (clientId, scheduleId, body) =>
	api.post(`${base(clientId)}/budget-schedules/${scheduleId}/rules`, body);

export const updateBudgetRule = (clientId, ruleId, body) =>
	api.patch(`${base(clientId)}/budget-rules/${ruleId}`, body);

export const deleteBudgetRule = (clientId, ruleId) =>
	api.delete(`${base(clientId)}/budget-rules/${ruleId}`);

// Stops the schedule and puts the campaign back on its default budget. On a
// stop-after-window schedule it also restarts the campaign. Returns `{job_id}`.
export const resetBudgetSchedule = (clientId, scheduleId) =>
	api.post(`${base(clientId)}/budget-schedules/${scheduleId}/reset`);

// ── Bid rules (keyword automations) ─────────────────────────────────────────
export const createBidRule = (clientId, body) =>
	api.post(`${base(clientId)}/bid-rules`, body);

export const updateBidRule = (clientId, ruleId, body) =>
	api.patch(`${base(clientId)}/bid-rules/${ruleId}`, body);

// `reset` also puts the keyword's bid back to the rule's min_bid before the rule goes.
// Without it the bid stays wherever the optimizer left it and no rule remains to lower it.
export const deleteBidRule = (clientId, ruleId, { reset = false } = {}) =>
	api.delete(`${base(clientId)}/bid-rules/${ruleId}`, { params: { reset } });

// pause | resume, and nothing else — anything else 404s. The engine holds exactly two
// states for a bid rule, active and paused, so there is no "stop" to send (the lifecycle
// block in campaign_manager_service.py is the contract).
export const setBidState = (clientId, ruleId, action) =>
	api.post(`${base(clientId)}/bid-rules/${ruleId}/${action}`);

// Bid back to the rule's min_bid. Enqueues a write and returns `{job_id}`; the engine
// refuses with 409 while the rule is running, because the next tick would undo it.
export const resetBidRule = (clientId, ruleId) =>
	api.post(`${base(clientId)}/bid-rules/${ruleId}/reset`);

// ── On-demand actions (enqueue → poll) ───────────────────────────────────────
export const setBudgetNow = (clientId, body) =>
	api.post(`${base(clientId)}/set-budget`, body);

export const setActivationNow = (clientId, campaignId, body) =>
	api.post(`${base(clientId)}/campaigns/${campaignId}/activation`, body);

export const runEngine = (clientId, which) =>
	api.post(`${base(clientId)}/run/${which}`);

export const refreshCampaigns = (clientId) =>
	api.post(`${base(clientId)}/campaigns/refresh`);

/**
 * The dark-store catalogue, which is where the evaluation-city suggestions come from.
 *
 * ⚠️ Read from the STORE catalogue, not from a city list. The catalogue is the only source
 * that reflects where stores actually are; a standalone city table drifts from it.
 * The engine resolves an evaluation city by lower-casing it against this same table
 * (`repo.py::resolve_store`), so a city offered here is one it can genuinely measure at.
 *
 * Not client-scoped: these are the platform's stores, not this account's.
 */
export const getStoreCatalogue = () => api.get("/reference/blinkit-zones");
