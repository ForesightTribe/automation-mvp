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

/** Account users — account-scoped, no client id. All admin-only server side. */
const users = "/account/users";

export const getAccountUsers = () => api.get(users);

export const createAccountUser = (body) => api.post(users, body);

export const setUserRole = (userId, role) =>
	api.patch(`${users}/${userId}/role`, { role });

export const setUserActive = (userId, isActive) =>
	api.patch(`${users}/${userId}/active`, { is_active: isActive });

/** `clientIds = null` means every client on the account. */
export const setUserClients = (userId, clientIds) =>
	api.put(`${users}/${userId}/clients`, { client_ids: clientIds });

/** ⚠️ Permanent. Deactivation is the reversible option. */
export const deleteAccountUser = (userId) => api.delete(`${users}/${userId}`);

/** Admin-set password for someone who cannot sign in. */
export const resetUserPassword = (userId, newPassword) =>
	api.post(`${users}/${userId}/password`, { new_password: newPassword });

/** Your own password. Requires the current one — a stray token is not proof. */
export const changeOwnPassword = (currentPassword, newPassword) =>
	api.post("/auth/password", {
		current_password: currentPassword,
		new_password: newPassword,
	});
