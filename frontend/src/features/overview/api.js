import { api } from "../../lib/axios";

/**
 * Endpoints this page calls. Thin wrappers over the shared `api` client — every
 * feature owns its own api.js so the page never touches HTTP/paths directly. All
 * private routes are under /clients/{clientId}/... (see api-reference.md).
 *
 * The overview window is sent as ?start=&end= (PeriodDep) and the marketplace
 * selection as a comma-separated ?marketplaces= (omitted = all).
 */
export const getOverview = (clientId, { start, end, marketplaces } = {}) =>
	api.get(`/clients/${clientId}/analytics/overview`, {
		params: {
			start,
			end,
			marketplaces: marketplaces?.length
				? marketplaces.join(",")
				: undefined,
		},
	});

export const getMarketplaceBreakdown = (clientId, { start, end } = {}) =>
	api.get(`/clients/${clientId}/overview/marketplaces`, {
		params: { start, end },
	});

export const getRevenue = (clientId, { start, end, marketplaces } = {}) =>
	api.get(`/clients/${clientId}/analytics/revenue`, {
		params: {
			start,
			end,
			marketplaces: marketplaces?.length
				? marketplaces.join(",")
				: undefined,
		},
	});

/** Unified daily series (ad spend/sales/impressions + revenue/units) for the
 * Overview charts and KPI sparklines. */
export const getTrends = (clientId, { start, end, marketplaces } = {}) =>
	api.get(`/clients/${clientId}/analytics/trends`, {
		params: {
			start,
			end,
			marketplaces: marketplaces?.length
				? marketplaces.join(",")
				: undefined,
		},
	});

/** Daily revenue per marketplace over a window — one series each. */
export const getMarketplaceTrends = (
	clientId,
	{ start, end, marketplaces } = {},
) =>
	api.get(`/clients/${clientId}/overview/marketplace-trends`, {
		params: {
			start,
			end,
			marketplaces: marketplaces?.length
				? marketplaces.join(",")
				: undefined,
		},
	});

export const getFreshness = (clientId) =>
	api.get(`/clients/${clientId}/overview/freshness`);

/** Action Center — typed, ranked insights with their evidence. */
export const getInsights = (clientId, { start, end } = {}) =>
	api.get(`/clients/${clientId}/overview/insights`, {
		params: { start, end },
	});

/** Weekly on-shelf availability — the public scrape's own granularity. */
export const getAvailabilityHistory = (clientId, { weeks = 8 } = {}) =>
	api.get(`/clients/${clientId}/inventory/availability-history`, {
		params: { weeks },
	});

/** Campaign rollup for a window — used for the ads breakdown. */
export const getCampaigns = (
	clientId,
	{ start, end, sort = "sales", limit = 8, marketplaces } = {},
) =>
	api.get(`/clients/${clientId}/ads/campaigns`, {
		params: {
			start,
			end,
			sort,
			order: "desc",
			page: 1,
			limit,
			recent_only: true,
			marketplaces: marketplaces?.length
				? marketplaces.join(",")
				: undefined,
		},
	});

/** Purchase-order headline figures for a window, against the one before it. */
export const getPoSummary = (clientId, { start, end } = {}) =>
	api.get(`/clients/${clientId}/purchase-orders/insights/summary`, {
		params: { start, end },
	});

/** The same figures, one row per marketplace whose POs are read separately. */
export const getPoByMarketplace = (
	clientId,
	{ start, end, marketplaces } = {},
) =>
	api.get(`/clients/${clientId}/purchase-orders/insights/by-marketplace`, {
		params: {
			start,
			end,
			marketplaces: marketplaces?.length
				? marketplaces.join(",")
				: undefined,
		},
	});

/** Share of voice for a window: headline figures plus the scraped days behind them. */
export const getShareOfVoice = (clientId, { start, end, marketplaces } = {}) =>
	api.get(`/clients/${clientId}/competition/share-of-voice`, {
		params: {
			start,
			end,
			marketplaces: marketplaces?.length
				? marketplaces.join(",")
				: undefined,
		},
	});

/** Who else shows up in our searches, ranked by presence. */
export const getTopCompetitors = (clientId, { start, end, limit = 6 } = {}) =>
	api.get(`/clients/${clientId}/competition/top-competitors`, {
		params: { start, end, limit },
	});

/** The same leaderboard, split by the marketplace each presence was seen on. */
export const getTopCompetitorsByMarketplace = (
	clientId,
	{ start, end, marketplaces, limit = 15 } = {},
) =>
	api.get(`/clients/${clientId}/competition/top-competitors/by-marketplace`, {
		params: {
			start,
			end,
			limit,
			marketplaces: marketplaces?.length
				? marketplaces.join(",")
				: undefined,
		},
	});

/** Our price against the competitor band, per keyword. */
export const getPricePosition = (
	clientId,
	{ start, end, marketplaces, byMarketplace } = {},
) =>
	api.get(`/clients/${clientId}/competition/price-position`, {
		params: {
			start,
			end,
			by_marketplace: byMarketplace || undefined,
			marketplaces: marketplaces?.length
				? marketplaces.join(",")
				: undefined,
		},
	});

/** Per own SKU: how many covered stores list it, and how many hold stock. */
export const getDistribution = (clientId, { start, end, marketplaces } = {}) =>
	api.get(`/clients/${clientId}/inventory/distribution`, {
		params: {
			start,
			end,
			kind: "main",
			marketplaces: marketplaces?.length
				? marketplaces.join(",")
				: undefined,
		},
	});

/** Reach and in-stock rate per marketplace, each against its own coverage. */
export const getDistributionByMarketplace = (
	clientId,
	{ start, end, marketplaces } = {},
) =>
	api.get(`/clients/${clientId}/inventory/distribution/by-marketplace`, {
		params: {
			start,
			end,
			marketplaces: marketplaces?.length
				? marketplaces.join(",")
				: undefined,
		},
	});
