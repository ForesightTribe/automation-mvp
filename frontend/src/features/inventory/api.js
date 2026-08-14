import { api } from "../../lib/axios";

/**
 * Inventory endpoints. The public own-SKU surface (from sku_snapshots, populated by
 * the `public-skus` scrape) all sit under /clients/{clientId}/inventory and take the
 * window as ?start=&end=, with optional ?city=/comma-separated ?marketplaces= (omitted
 * = all). `?kind=` splits singular main SKUs from combos/multipacks (main | combo |
 * all; default main) — combos are stocked selectively so they aren't compared against
 * main SKUs by default. Each response carries `as_of` for the freshness badge.
 *
 * The unit is the DARK STORE (`merchant_id`), not the coordinate we probed: one
 * coordinate can be served by several stores and one store can answer several
 * coordinates. Responses ship the denominators (`stores_scraped`, `active_range`)
 * alongside every percentage so the UI can always render "X of N" — never a bare
 * percentage. See docs/darkstores.md.
 */
const params = ({ start, end, marketplaces, ...rest } = {}) => ({
	start,
	end,
	marketplaces: marketplaces?.length ? marketplaces.join(",") : undefined,
	...rest,
});

export const getDistribution = (clientId, opts) =>
	api.get(`/clients/${clientId}/inventory/distribution`, { params: params(opts) });

export const getAvailability = (clientId, opts) =>
	api.get(`/clients/${clientId}/inventory/availability`, { params: params(opts) });

export const getAvailabilityHistory = (clientId, opts) =>
	api.get(`/clients/${clientId}/inventory/availability-history`, {
		params: params(opts),
	});

export const getPricing = (clientId, opts) =>
	api.get(`/clients/${clientId}/inventory/pricing`, { params: params(opts) });

/** Availability per dark store, worst first. `tier` narrows to one fulfilment tier. */
export const getStores = (clientId, opts) =>
	api.get(`/clients/${clientId}/inventory/stores`, { params: params(opts) });

/** The same numbers rolled up one level, for the city view. */
export const getCities = (clientId, opts) =>
	api.get(`/clients/${clientId}/inventory/cities`, { params: params(opts) });

/**
 * The work queue — one row per problem, naming a store and a product.
 * `action=oos` (listed but empty → replenishment) or `not-listed` (absent from the
 * shelf → range). Two separate lists on purpose: different teams act on them.
 * Server-paginated.
 */
export const getActions = (clientId, opts) =>
	api.get(`/clients/${clientId}/inventory/actions`, { params: params(opts) });

/** One store's whole shelf — absent SKUs included, flagged `listed: false`. */
export const getStoreDetail = (clientId, merchantId, opts) =>
	api.get(`/clients/${clientId}/inventory/stores/${merchantId}`, {
		params: params(opts),
	});

/** One product across every store — where it's OOS, not carried, or fine. */
export const getProductStores = (clientId, productId, opts) =>
	api.get(`/clients/${clientId}/inventory/products/${productId}/stores`, {
		params: params(opts),
	});
