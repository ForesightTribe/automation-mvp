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

export const getMonthlyTrends = (clientId, { months = 3 } = {}) =>
	api.get(`/clients/${clientId}/overview/monthly-trends`, {
		params: { months },
	});

export const getFreshness = (clientId) =>
	api.get(`/clients/${clientId}/overview/freshness`);

export const getAlerts = (clientId) =>
	api.get(`/clients/${clientId}/overview/alerts`);

/** Public on-shelf distribution (own SKUs, from sku_snapshots) for the Overview
 * summary card. Weekly scrape, so it takes ?days= not the start/end window. */
export const getPublicShelf = (clientId, { days } = {}) =>
	api.get(`/clients/${clientId}/inventory/distribution`, { params: { days } });
