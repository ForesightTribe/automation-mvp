import { api } from "../../lib/axios";

/**
 * Reports endpoints. Thin wrappers over the shared `api` client (which unwraps
 * response.data). All private routes are under /clients/{clientId}/reports/...
 *
 * The window is sent as ?start=&end= (PeriodDep) and the marketplace selection
 * as a comma-separated ?marketplaces= (omitted = all).
 */
export const getSalesPivot = (clientId, { start, end, marketplaces, metric } = {}) =>
	api.get(`/clients/${clientId}/reports/sales-pivot`, {
		params: {
			start,
			end,
			metric,
			marketplaces: marketplaces?.length
				? marketplaces.join(",")
				: undefined,
		},
	});

export const getMarketing = (clientId, { start, end, marketplaces } = {}) =>
	api.get(`/clients/${clientId}/reports/marketing`, {
		params: {
			start,
			end,
			marketplaces: marketplaces?.length
				? marketplaces.join(",")
				: undefined,
		},
	});

export const getCompetition = (clientId, { start, end, marketplaces, kind } = {}) =>
	api.get(`/clients/${clientId}/reports/competition`, {
		params: {
			start,
			end,
			kind,
			marketplaces: marketplaces?.length
				? marketplaces.join(",")
				: undefined,
		},
	});
