import { api } from "../../lib/axios";

/**
 * Endpoints the Sales & Analytics page calls. Every private route is under
 * /clients/{clientId}/analytics/... (see api-reference.md). The reporting window
 * is sent as ?start=&end= (PeriodDep) and the marketplace selection as a
 * comma-separated ?marketplaces= (omitted = all).
 */
const params = ({ start, end, marketplaces, ...rest } = {}) => ({
	start,
	end,
	marketplaces: marketplaces?.length ? marketplaces.join(",") : undefined,
	...rest,
});

/** Headline KPIs (revenue, units, SKUs, ad spend/RoAS, …) as {value, prev, delta_pct}. */
export const getOverview = (clientId, opts) =>
	api.get(`/clients/${clientId}/analytics/overview`, { params: params(opts) });

/** Unified daily series (ad spend/sales/impressions + revenue/units) for sparklines. */
export const getTrends = (clientId, opts) =>
	api.get(`/clients/${clientId}/analytics/trends`, { params: params(opts) });

/** Daily revenue + units time-series. */
export const getRevenue = (clientId, opts) =>
	api.get(`/clients/${clientId}/analytics/revenue`, { params: params(opts) });

export const getTopSkus = (clientId, opts) =>
	api.get(`/clients/${clientId}/analytics/top-skus`, { params: params(opts) });

export const getSalesByCity = (clientId, opts) =>
	api.get(`/clients/${clientId}/analytics/sales-by-city`, {
		params: params(opts),
	});

export const getSalesByCategory = (clientId, opts) =>
	api.get(`/clients/${clientId}/analytics/sales-by-category`, {
		params: params(opts),
	});

export const getCategoryTrend = (clientId, opts) =>
	api.get(`/clients/${clientId}/analytics/category-trend`, {
		params: params(opts),
	});

export const getCityCategory = (clientId, opts) =>
	api.get(`/clients/${clientId}/analytics/city-category`, {
		params: params(opts),
	});
