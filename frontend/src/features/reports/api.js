import { api } from "../../lib/axios";

/**
 * Reports endpoints. Thin wrappers over the shared `api` client (which unwraps
 * response.data). All private routes are under /clients/{clientId}/reports/...
 *
 * The window is sent as ?start=&end= (PeriodDep) and the marketplace selection
 * as a comma-separated ?marketplaces= (omitted = all).
 */
export const getSalesPivot = (
	clientId,
	{ start, end, marketplaces, metric } = {},
) =>
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

export const getCompetition = (
	clientId,
	{ start, end, marketplaces, kind } = {},
) =>
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

/**
 * The report currently on screen, as an .xlsx.
 *
 * ⚠️ Every parameter mirrors a control on the page. The server renders from the
 * same service that fed the table, so the file is the report the reader was
 * looking at rather than a second interpretation of the same window.
 *
 * `responseType: "blob"` is not optional: without it axios parses the body as
 * text and the workbook arrives corrupt, which surfaces as "Excel cannot open
 * this file" rather than as an error anyone can trace.
 */
export const getWeekendPlanning = (
	clientId,
	{ start, end, marketplaces } = {},
) =>
	api.get(`/clients/${clientId}/reports/weekend-planning`, {
		params: {
			start,
			end,
			marketplaces: marketplaces?.length
				? marketplaces.join(",")
				: undefined,
		},
	});

export const getRawAds = (
	clientId,
	{ start, end, campaignType, page, limit } = {},
) =>
	api.get(`/clients/${clientId}/reports/raw-ads`, {
		params: { start, end, campaign_type: campaignType, page, limit },
	});

export const getReportFile = (
	clientId,
	which,
	{ start, end, marketplaces, metric, view, kind } = {},
) =>
	api.get(`/clients/${clientId}/reports/${which}/file`, {
		params: {
			start,
			end,
			metric,
			view,
			kind,
			marketplaces: marketplaces?.length
				? marketplaces.join(",")
				: undefined,
		},
		responseType: "blob",
	});
