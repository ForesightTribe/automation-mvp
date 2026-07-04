import { api } from "../../lib/axios";

/**
 * Inventory endpoints. The public own-SKU surface (from sku_snapshots, populated by
 * the weekly `public-skus` scrape) all under /clients/{clientId}/inventory and take
 * the window as ?days=, with optional ?city=/?marketplace=. `?kind=` splits singular
 * main SKUs from combos/multipacks (main | combo | all; default main) — combos are
 * stocked selectively so they aren't compared against main SKUs by default.
 * `/availability` is server-paginated (?page=&limit=); the rest return the full small
 * per-SKU set. Each response carries `as_of` for the freshness badge.
 */
export const getDistribution = (clientId, { days, city, marketplace, kind } = {}) =>
	api.get(`/clients/${clientId}/inventory/distribution`, {
		params: { days, city, marketplace, kind },
	});

export const getAvailability = (
	clientId,
	{ days, city, marketplace, kind, page, limit } = {},
) =>
	api.get(`/clients/${clientId}/inventory/availability`, {
		params: { days, city, marketplace, kind, page, limit },
	});

export const getAvailabilityHistory = (
	clientId,
	{ days, city, marketplace, kind } = {},
) =>
	api.get(`/clients/${clientId}/inventory/availability-history`, {
		params: { days, city, marketplace, kind },
	});

export const getPricing = (clientId, { days, city, marketplace, kind } = {}) =>
	api.get(`/clients/${clientId}/inventory/pricing`, {
		params: { days, city, marketplace, kind },
	});
