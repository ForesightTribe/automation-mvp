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

// Zepto-only: keyword performance. Separate from getKeywords because Zepto's
// keyword grain has no campaign dimension and no direct/indirect sales split,
// so it is served by its own endpoint rather than widening the shared one.
export const getZeptoKeywords = (
	clientId,
	{ start, end, sort, order, limit } = {},
) =>
	api.get(`/clients/${clientId}/ads/zepto-keywords`, {
		params: { start, end, sort, order, limit },
	});

// Zepto-only: spend + RoAS per campaign type (PLA / Display) for the donut.
export const getZeptoBudgetSplit = (clientId, { start, end } = {}) =>
	api.get(`/clients/${clientId}/ads/zepto-budget-split`, {
		params: { start, end },
	});

// Zepto-only: share of voice + ad position per campaign. A trailing snapshot,
// not a windowed figure — the dates only bound which scrapes are considered.
export const getZeptoSov = (clientId, { start, end } = {}) =>
	api.get(`/clients/${clientId}/ads/zepto-sov`, { params: { start, end } });

// Zepto-only: per-SKU and per-retail-category ad performance. `campaignCategory`
// narrows to one ad type; omit it to combine all three.
export const getZeptoProducts = (
	clientId,
	{ start, end, campaignCategory, limit } = {},
) =>
	api.get(`/clients/${clientId}/ads/zepto-products`, {
		params: { start, end, campaign_category: campaignCategory || undefined, limit },
	});

export const getZeptoBreakdown = (
	clientId,
	{ start, end, dimension, campaignCategory } = {},
) =>
	api.get(`/clients/${clientId}/ads/zepto-breakdown`, {
		params: {
			start,
			end,
			dimension,
			campaign_category: campaignCategory || undefined,
		},
	});
