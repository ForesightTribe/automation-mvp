import { api } from "../../lib/axios";

/**
 * Ad Automation endpoints. Thin wrappers over the shared `api` client (see
 * features/ads/api.js for the pattern). All routes are under
 * /clients/{clientId}/ad-automation. Rules are plain CRUD; `evaluateNow` and
 * `resolveAction` are the two mutations — everything else is a read.
 */
export const getRules = (clientId) =>
	api.get(`/clients/${clientId}/ad-automation/rules`);

export const createRule = (clientId, payload) =>
	api.post(`/clients/${clientId}/ad-automation/rules`, payload);

export const updateRule = (clientId, ruleId, payload) =>
	api.put(`/clients/${clientId}/ad-automation/rules/${ruleId}`, payload);

export const deleteRule = (clientId, ruleId) =>
	api.delete(`/clients/${clientId}/ad-automation/rules/${ruleId}`);

export const evaluateNow = (clientId) =>
	api.post(`/clients/${clientId}/ad-automation/evaluate`);

export const getActions = (clientId, { status, page, limit } = {}) =>
	api.get(`/clients/${clientId}/ad-automation/actions`, {
		params: { status: status || undefined, page, limit },
	});

export const resolveAction = (clientId, actionId, status) =>
	api.patch(`/clients/${clientId}/ad-automation/actions/${actionId}`, {
		status,
	});
