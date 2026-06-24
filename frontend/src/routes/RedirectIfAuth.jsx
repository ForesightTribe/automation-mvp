import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { Loading } from "../components/feedback/Loading";

/**
 * Inverse of RequireAuth. Wraps the public routes (`/` landing, `/login`): a
 * logged-in user has no business there, so send them straight to the dashboard.
 * Waits out the boot session check to avoid flashing the public page.
 */
export const RedirectIfAuth = () => {
	const { isAuthenticated, loading } = useAuth();

	if (loading)
		return <Loading label="Checking session…" className="h-screen" />;
	if (isAuthenticated) return <Navigate to="/overview" replace />;
	return <Outlet />;
};
