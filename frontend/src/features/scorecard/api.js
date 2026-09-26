import { api } from "../../lib/axios";

/**
 * Scorecard endpoints — a marketplace's view of brand health. Thin wrappers over
 * the shared `api` client (see ads/api.js for the pattern). All routes are under
 * /clients/{clientId}/scorecard.
 *
 * Scorecard data is **weekly snapshots**, so these reads navigate by week
 * (`from` = a `from_date_ist`, defaulting to latest) rather than the global date
 * range.
 *
 * `marketplace` is optional — omit it (undefined) for the backend's own
 * auto-detect (Blinkit if it publishes one for this tenant, else Zepto).
 * Instamart is explicit-only: it's never auto-detected, since a tenant can have
 * BOTH Zepto and Instamart PO data and guessing between two derived sources
 * would be ambiguous. See `scorecard_service._platform`'s docstring.
 */
export const getWeeks = (clientId, { marketplace } = {}) =>
	api.get(`/clients/${clientId}/scorecard/weeks`, { params: { marketplace } });

export const getWeekly = (clientId, { from, marketplace } = {}) =>
	api.get(`/clients/${clientId}/scorecard/weekly`, {
		params: { from, marketplace },
	});

export const getTrend = (clientId, { weeks, marketplace } = {}) =>
	api.get(`/clients/${clientId}/scorecard/trend`, {
		params: { weeks, marketplace },
	});

export const getKeySkus = (clientId, { from, page, limit, marketplace } = {}) =>
	api.get(`/clients/${clientId}/scorecard/key-skus`, {
		params: { from, page, limit, marketplace },
	});

export const getFacilities = (clientId, { from, page, limit, marketplace } = {}) =>
	api.get(`/clients/${clientId}/scorecard/facilities`, {
		params: { from, page, limit, marketplace },
	});

export const getFacilityPos = (
	clientId,
	facilityId,
	{ page, limit, marketplace } = {},
) =>
	api.get(
		`/clients/${clientId}/scorecard/facility/${facilityId}/pos`,
		{ params: { page, limit, marketplace } },
	);
