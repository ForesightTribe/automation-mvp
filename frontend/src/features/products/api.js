import { api } from "../../lib/axios";

/**
 * Endpoints the Products page calls — all under /clients/{clientId}/products
 * (private plane, keyed on item_id). The reporting window goes as ?start=&end=
 * (PeriodDep) and the marketplace selection as comma-separated ?marketplaces=
 * (omitted = all); list filters (page/limit/sort/sku_status/search) ride along.
 */
const params = ({ start, end, marketplaces, ...rest } = {}) => ({
	start,
	end,
	marketplaces: marketplaces?.length ? marketplaces.join(",") : undefined,
	...rest,
});

/** Paginated SKU list + KPI summary: `{ summary, products: Page }`. */
export const getProducts = (clientId, opts) =>
	api.get(`/clients/${clientId}/products`, { params: params(opts) });

/** Product 360 for one SKU: totals, stock, cover, trends, facility/city splits. */
export const getProductDetail = (clientId, itemId, opts) =>
	api.get(`/clients/${clientId}/products/${itemId}`, {
		params: params(opts),
	});

/** Paginated PO line history for one SKU. */
export const getProductPos = (clientId, itemId, opts) =>
	api.get(`/clients/${clientId}/products/${itemId}/pos`, {
		params: params(opts),
	});
