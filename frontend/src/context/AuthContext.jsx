import {
	createContext,
	useContext,
	useEffect,
	useState,
	useCallback,
} from "react";
import { api } from "../lib/axios";
import { STORAGE_KEYS, AUTH_EXPIRED_EVENT } from "../lib/constants";
import { logger } from "../lib/logger";

/**
 * Owns authentication: the JWT and the current user. This is genuine app-owned
 * client state (not server cache), so it lives in Context — not React Query.
 * Server data (dashboards) is fetched per-feature with useQuery.
 *
 * Provider + hook live together in one file by choice. (Fast Refresh prefers
 * components-only modules; the `only-export-components` lint rule is disabled
 * for that reason — a full reload on edits to this file is fine.)
 */
const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
	const [token, setToken] = useState(() =>
		localStorage.getItem(STORAGE_KEYS.token),
	);
	const [user, setUser] = useState(null);
	// `loading` covers the initial "do we have a valid session?" check on boot.
	const [loading, setLoading] = useState(Boolean(token));

	// On boot (or token change), resolve the current user from the token.
	useEffect(() => {
		if (!token) {
			setUser(null);
			setLoading(false);
			return;
		}
		let cancelled = false;
		setLoading(true);
		api.get("/auth/me")
			.then((me) => !cancelled && setUser(me))
			.catch((err) => {
				// Token invalid/expired — drop it.
				logger.warn("session check failed, clearing token", err);
				if (!cancelled) {
					localStorage.removeItem(STORAGE_KEYS.token);
					setToken(null);
					setUser(null);
				}
			})
			.finally(() => !cancelled && setLoading(false));
		return () => {
			cancelled = true;
		};
	}, [token]);

	const login = useCallback(async (email, password) => {
		// Backend returns the JWT; field assumed `access_token` (verify vs API).
		const res = await api.post("/auth/login", { email, password });
		localStorage.setItem(STORAGE_KEYS.token, res.access_token);
		setToken(res.access_token); // triggers the /auth/me effect above
		return res;
	}, []);

	// Drop all session state locally (no server call). Used by logout and by the
	// 401 session-expiry path.
	const clearSession = useCallback(() => {
		localStorage.removeItem(STORAGE_KEYS.token);
		localStorage.removeItem(STORAGE_KEYS.activeClientId);
		setToken(null);
		setUser(null);
	}, []);

	const logout = useCallback(() => {
		api.post("/auth/logout").catch(() => {}); // stateless; best-effort
		clearSession();
	}, [clearSession]);

	// The axios layer fires AUTH_EXPIRED_EVENT on a 401 with a stale token.
	// End the session here; RequireAuth then bounces to /login.
	useEffect(() => {
		const onExpired = () => {
			logger.warn("session expired (401) — logging out");
			clearSession();
		};
		window.addEventListener(AUTH_EXPIRED_EVENT, onExpired);
		return () => window.removeEventListener(AUTH_EXPIRED_EVENT, onExpired);
	}, [clearSession]);

	const value = {
		token,
		user,
		loading,
		isAuthenticated: Boolean(token),
		login,
		logout,
	};

	return (
		<AuthContext.Provider value={value}>{children}</AuthContext.Provider>
	);
};

export const useAuth = () => {
	const ctx = useContext(AuthContext);
	if (!ctx) throw new Error("useAuth must be used within <AuthProvider>");
	return ctx;
};
