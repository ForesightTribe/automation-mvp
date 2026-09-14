import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { Loading } from "../components/feedback/Loading";

/**
 * Route guard. Wraps the authenticated app: while the boot session check runs
 * it shows a spinner; if there's no session it redirects to /login, passing the
 * attempted route as `from` so signing in returns the reader to where they were
 * headed rather than to the dashboard's front page.
 */
export const RequireAuth = () => {
	const { isAuthenticated, loading } = useAuth();
	const location = useLocation();

	if (loading)
		return <Loading label="Checking session…" className="h-screen" />;
	if (!isAuthenticated)
		return <Navigate to="/login" replace state={{ from: location }} />;
	return <Outlet />;
};
