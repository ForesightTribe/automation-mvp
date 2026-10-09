import { api } from "../../lib/axios";

/** Settings — the endpoints behind the client's marketplace connections. */
const base = (clientId) => `/clients/${clientId}/platforms`;

export const getPlatforms = (clientId) => api.get(base(clientId));

// Write-only: no endpoint reads a password back.
export const saveCredentials = (clientId, platform, body) =>
	api.put(`${base(clientId)}/${platform}/credentials`, body);

/** Start a login. Returns `{job_id}` to poll — the sign-in runs as a job. */
export const startLogin = (clientId, platform) =>
	api.post(`${base(clientId)}/${platform}/login`);

export const disconnect = (clientId, platform) =>
	api.delete(`${base(clientId)}/${platform}`);

export const getJob = (clientId, jobId) =>
	api.get(`/clients/${clientId}/campaign-manager/jobs/${jobId}`);
