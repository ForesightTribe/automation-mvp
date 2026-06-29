import { api } from "../../lib/axios";

/**
 * Ads endpoints. Thin wrappers over the shared `api` client (see overview/api.js
 * for the pattern). All routes are under /clients/{clientId}/ads. Window endpoints
 * send the date range as ?start=&end= (PeriodDep) and the marketplace selection as
 * a comma-separated ?marketplaces= (omitted = all). Keyword/plan/collection reads
 * are snapshot-based and take no date range.
 */
const mp = (marketplaces) =>
	marketplaces?.length ? marketplaces.join(",") : undefined;

export const getSummary = (clientId, { start, end, marketplaces } = {}) =>
	api.get(`/clients/${clientId}/ads/summary`, {
		params: { start, end, marketplaces: mp(marketplaces) },
	});

export const getPerformance = (clientId, { start, end, marketplaces } = {}) =>
	api.get(`/clients/${clientId}/ads/performance`, {
		params: { start, end, marketplaces: mp(marketplaces) },
	});

export const getBudgetSplit = (clientId, { start, end, marketplaces } = {}) =>
	api.get(`/clients/${clientId}/ads/budget-split`, {
		params: { start, end, marketplaces: mp(marketplaces) },
	});

export const getCampaigns = (
	clientId,
	{ start, end, marketplaces, page, limit, status, sort, order } = {},
) =>
	api.get(`/clients/${clientId}/ads/campaigns`, {
		params: {
			start,
			end,
			marketplaces: mp(marketplaces),
			page,
			limit,
			status: status || undefined,
			sort,
			order,
		},
	});

export const getKeywords = (
	clientId,
	{ marketplaces, page, limit, campaignId, targetType, sort, order } = {},
) =>
	api.get(`/clients/${clientId}/ads/keywords`, {
		params: {
			marketplaces: mp(marketplaces),
			page,
			limit,
			campaign_id: campaignId || undefined,
			target_type: targetType || undefined,
			sort,
			order,
		},
	});

export const getSov = (clientId, { start, end, marketplaces } = {}) =>
	api.get(`/clients/${clientId}/ads/sov`, {
		params: { start, end, marketplaces: mp(marketplaces) },
	});

export const getMarketplaceBreakdown = (clientId, { start, end } = {}) =>
	api.get(`/clients/${clientId}/ads/marketplaces`, {
		params: { start, end },
	});

export const getVisibilityPlans = (clientId) =>
	api.get(`/clients/${clientId}/ads/visibility-plans`);

export const getCollections = (clientId) =>
	api.get(`/clients/${clientId}/ads/collections`);
