import { api } from "../../lib/axios";

/**
 * Scorecard endpoints — "Blinkit's view of my brand health". Thin wrappers over
 * the shared `api` client (see ads/api.js for the pattern). All routes are under
 * /clients/{clientId}/scorecard.
 *
 * Scorecard data is **weekly snapshots**, so these reads navigate by week
 * (`from` = a `from_date_ist`, defaulting to latest) rather than the global date
 * range. Blinkit-only, so there's no marketplace param.
 */
export const getWeeks = (clientId) =>
	api.get(`/clients/${clientId}/scorecard/weeks`);

export const getWeekly = (clientId, { from } = {}) =>
	api.get(`/clients/${clientId}/scorecard/weekly`, { params: { from } });

export const getTrend = (clientId, { weeks } = {}) =>
	api.get(`/clients/${clientId}/scorecard/trend`, { params: { weeks } });

export const getKeySkus = (clientId, { from, page, limit } = {}) =>
	api.get(`/clients/${clientId}/scorecard/key-skus`, {
		params: { from, page, limit },
	});

export const getFacilities = (clientId, { from, page, limit } = {}) =>
	api.get(`/clients/${clientId}/scorecard/facilities`, {
		params: { from, page, limit },
	});

export const getFacilityPos = (clientId, facilityId, { page, limit } = {}) =>
	api.get(
		`/clients/${clientId}/scorecard/facility/${facilityId}/pos`,
		{ params: { page, limit } },
	);
