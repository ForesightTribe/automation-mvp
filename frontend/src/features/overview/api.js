import { api } from "../../lib/axios";
import { DEFAULT_DAYS } from "../../lib/constants";

/**
 * Endpoints this page calls. Thin wrappers over the shared `api` client — every
 * feature owns its own api.js so the page never touches HTTP/paths directly. All
 * private routes are under /clients/{clientId}/... (see api-reference.md).
 */
export const getOverview = (clientId, { days = DEFAULT_DAYS } = {}) =>
	api.get(`/clients/${clientId}/analytics/overview`, {
		params: { days },
	});

export const getAlerts = (clientId) =>
	api.get(`/clients/${clientId}/overview/alerts`);
