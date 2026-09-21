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
		},
	});

export const getPoSkus = (
	clientId,
	{ start, end, search, page = 1, limit = 25 } = {},
) =>
	api.get(`${base(clientId)}/insights/skus`, {
		params: { start, end, search: search || undefined, page, limit },
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
