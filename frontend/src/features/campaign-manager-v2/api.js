import { api } from "../../lib/axios";

/**
 * Campaign Manager v2 endpoints — thin wrappers over the shared `api` client.
 * All under /clients/{clientId}/campaign-manager (see api-reference). The response
 * interceptor unwraps `.data`, so each call resolves to the payload directly.
 *
 * The backend is thin: rule edits only write DB rows + enqueue `cm.reconcile`;
 * on-demand actions enqueue a job and return `{ job_id }` for the UI to poll.
 */
const base = (clientId) => `/clients/${clientId}/campaign-manager`;

// ── Budget schedules + rules ────────────────────────────────────────────────
export const getBudgetSchedules = (clientId) => api.get(`${base(clientId)}/budget-schedules`);

export const createBudgetSchedule = (clientId, body) =>
	api.post(`${base(clientId)}/budget-schedules`, body);

export const deleteBudgetSchedule = (clientId, scheduleId) =>
	api.delete(`${base(clientId)}/budget-schedules/${scheduleId}`);

export const updateBudgetSchedule = (clientId, scheduleId, body) =>
	api.patch(`${base(clientId)}/budget-schedules/${scheduleId}`, body);

export const addBudgetRule = (clientId, scheduleId, body) =>
	api.post(`${base(clientId)}/budget-schedules/${scheduleId}/rules`, body);

export const updateBudgetRule = (clientId, ruleId, body) =>
	api.patch(`${base(clientId)}/budget-rules/${ruleId}`, body);

export const deleteBudgetRule = (clientId, ruleId) =>
	api.delete(`${base(clientId)}/budget-rules/${ruleId}`);

export const resetBudgetSchedule = (clientId, scheduleId) =>
	api.post(`${base(clientId)}/budget-schedules/${scheduleId}/reset`);

// ── Bid rules + D19 lifecycle ───────────────────────────────────────────────
export const getBidRules = (clientId) => api.get(`${base(clientId)}/bid-rules`);

export const createBidRule = (clientId, body) => api.post(`${base(clientId)}/bid-rules`, body);

export const updateBidRule = (clientId, ruleId, body) =>
	api.patch(`${base(clientId)}/bid-rules/${ruleId}`, body);

export const deleteBidRule = (clientId, ruleId) =>
	api.delete(`${base(clientId)}/bid-rules/${ruleId}`);

export const setBidState = (clientId, ruleId, action) =>
	api.post(`${base(clientId)}/bid-rules/${ruleId}/${action}`); // pause | resume | stop

// ── On-demand actions (enqueue → poll) ──────────────────────────────────────
export const setBudgetNow = (clientId, body) => api.post(`${base(clientId)}/set-budget`, body);

// Start / stop a campaign. body = { status: "running" | "paused", budget? }.
// `budget` is for a resume only — Blinkit's restart re-submits the campaign and sets its
// budget; omitting it lets the VM reuse the campaign's current one from a fresh read.
export const setActivationNow = (clientId, campaignId, body) =>
	api.post(`${base(clientId)}/campaigns/${campaignId}/activation`, body);

export const runEngine = (clientId, which) =>
	api.post(`${base(clientId)}/run/${which}`); // budget-scheduler | bid-optimizer

// ── Status + history ────────────────────────────────────────────────────────
export const getJob = (clientId, jobId) => api.get(`${base(clientId)}/jobs/${jobId}`);

export const getHistory = (clientId, { page = 1, limit = 20, kind } = {}) =>
	api.get(`${base(clientId)}/history`, { params: { page, limit, kind } });

// ── Advertiser account ──────────────────────────────────────────────────────
export const getAdvertiser = (clientId) => api.get(`${base(clientId)}/advertiser`);

export const setAdvertiser = (clientId, advertiserId) =>
	api.put(`${base(clientId)}/advertiser`, { advertiser_id: advertiserId });

// ── Campaign catalogue (for the name/id pickers) ────────────────────────────
// Reuses the Ads campaigns endpoint. A wide window (days=365) so campaigns without
// recent spend still list; the picker only needs id + name + status.
//
// `recent_only` keeps ONLY campaigns seen in the most recent catalogue sync, and it is
// what stops a dead account's campaigns from being selectable here. Dobra's dashboard
// moved to a new email in June 2026: the old account's 186 campaigns are still in the
// table (we never delete data) but can no longer be read or written, while 38 of their
// NAMES also exist in the live account — several reading ACTIVE on both sides. Picking
// one is unrecoverable-looking, so the write surfaces must never offer them.
//
// This filters on scrape freshness rather than an id cutoff because the catalogue comes
// from a single all-or-nothing list call: a campaign the account no longer returns keeps
// its old timestamp and drops out by itself. Ads Analytics deliberately does NOT filter —
// the client keeps their full pre-migration reporting history.
export const getCampaigns = (clientId) =>
	api.get(`/clients/${clientId}/ads/campaigns`, {
		params: { days: 365, limit: 250, sort: "spend", order: "desc", recent_only: true },
	});

// Refresh the campaign catalogue from the live account (enqueue → poll, like the other
// on-demand actions). One list call on the VM, not a full marketing scrape.
export const refreshCampaigns = (clientId) =>
	api.post(`${base(clientId)}/campaigns/refresh`);

export const getCampaignKeywords = (clientId, campaignId) =>
	api.get(`/clients/${clientId}/ads/campaigns/${campaignId}/keywords`);
