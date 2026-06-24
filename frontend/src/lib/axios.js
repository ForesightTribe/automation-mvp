import axios from "axios";
import { STORAGE_KEYS, AUTH_EXPIRED_EVENT } from "./constants";
import { logger } from "./logger";

/**
 * `api` — the single axios instance every API call goes through. Named by role
 * (not "axios") so call sites read `api.get(...)` and swapping the HTTP lib only
 * touches this file. Centralises:
 *   - base URL (from VITE_API_BASE_URL)
 *   - auth: attaches the Bearer token on every request
 *   - logging: traces each request/response in dev (silenced in prod)
 *   - error shape: rejects with a normalized Error { status, data } so callers
 *     (and React Query's `error`) always see the same fields
 *
 * The response interceptor unwraps `response.data`, so callers get the payload
 * directly: `const user = await api.get("/auth/me")`.
 */
export const api = axios.create({
	baseURL: import.meta.env.VITE_API_BASE_URL ?? "/api",
	headers: { "Content-Type": "application/json" },
});

// --- Request: attach token + trace ---
api.interceptors.request.use((config) => {
	const token = localStorage.getItem(STORAGE_KEYS.token);
	if (token) config.headers.Authorization = `Bearer ${token}`;
	logger.request(config.method, config.url);
	return config;
});

// --- Response: unwrap data, trace, normalize errors ---
api.interceptors.response.use(
	(response) => {
		logger.response(
			response.config.method,
			response.config.url,
			response.status,
		);
		return response.data;
	},
	(error) => {
		const status = error.response?.status ?? 0;
		// FastAPI errors are `{ detail: "..." }`; fall back for network failures.
		const message =
			error.response?.data?.detail ??
			(status === 0
				? "Network error — please check your connection."
				: `Request failed (${status})`);

		logger.error(
			"api error",
			status,
			error.config?.method,
			error.config?.url,
		);

		// Session expiry: a 401 *while we hold a token* means it's stale. Clear it
		// and signal AuthContext to end the session (RequireAuth then redirects).
		// Guarded by token presence so a 401 from the login attempt itself — bad
		// credentials, no token yet — is left for the login modal to show inline.
		if (status === 401 && localStorage.getItem(STORAGE_KEYS.token)) {
			localStorage.removeItem(STORAGE_KEYS.token);
			window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
		}

		// Plain Error (no custom class) carrying the normalized fields.
		return Promise.reject(
			Object.assign(new Error(message), {
				status,
				data: error.response?.data,
			}),
		);
	},
);
