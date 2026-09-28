import { api } from "../../lib/axios";

/** Purchase orders — the PO queue and the figures above it. */
const base = (clientId) => `/clients/${clientId}/purchase-orders`;

export const getPoSummary = (clientId, { start, end } = {}) =>
	api.get(`${base(clientId)}/insights/summary`, { params: { start, end } });

export const getPoInsights = (
	clientId,
	{
		start,
		end,
		scope = "priority",
		search,
		status,
		page = 1,
		limit = 25,
		sort,
		order,
	} = {},
) =>
	api.get(`${base(clientId)}/insights`, {
		params: {
			start,
			end,
			scope,
			search: search || undefined,
			status: status || undefined,
			page,
			limit,
			// Ordered server-side so a header sorts every PO, not the page.
			sort: sort || undefined,
			order: sort ? order : undefined,
		},
	});

export const getPoSkus = (
	clientId,
	{ start, end, search, page = 1, limit = 25, sort, order } = {},
) =>
	api.get(`${base(clientId)}/insights/skus`, {
		params: {
			start,
			end,
			search: search || undefined,
			page,
			limit,
			// Ordered server-side so a header sorts every SKU, not the page.
			sort: sort || undefined,
			order: sort ? order : undefined,
		},
	});

/**
 * The section as an .xlsx — the PO table and the SKU shortfall in one workbook.
 *
 * `responseType: "blob"` is not optional: without it axios parses the body as text and
 * the workbook arrives corrupt, which surfaces as "Excel cannot open this file".
 */
export const getPoFile = (
	clientId,
	{ start, end, scope = "priority", status } = {},
) =>
	api.get(`${base(clientId)}/insights/file`, {
		params: { start, end, scope, status: status || undefined },
		responseType: "blob",
	});

/** One PO with its line items — the drawer behind a row. */
export const getPo = (clientId, poNumber) =>
	api.get(`${base(clientId)}/${poNumber}`);

/** Every PO carrying one SKU — what the SKU drawer lists. */
export const getSkuPos = (clientId, itemId, { page = 1, limit = 50 } = {}) =>
	api.get(`/clients/${clientId}/products/${itemId}/pos`, {
		params: { page, limit },
	});
