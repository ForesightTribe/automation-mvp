import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { Loading } from "../components/feedback/Loading";

/**
 * Route guard. Wraps the authenticated app: while the boot session check runs
 * it shows a spinner; if there's no session it redirects to the landing page,
 * passing the attempted route as `from` so the landing page can auto-open the
 * login modal and send the user back there after signing in.
 */
export const RequireAuth = () => {
	const { isAuthenticated, loading } = useAuth();
	const location = useLocation();

	if (loading)
		return <Loading label="Checking session…" className="h-screen" />;
	if (!isAuthenticated)
		return <Navigate to="/" replace state={{ from: location }} />;
	return <Outlet />;
};
