import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { Loading } from "../components/feedback/Loading";

/**
 * Route guard. Wraps the authenticated app: while the boot session check runs
 * it shows a spinner; if there's no session it redirects to /login, preserving
 * where the user was headed.
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
