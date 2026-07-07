import { api } from "../../lib/axios";

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
