import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { Loading } from "../components/feedback/Loading";

/**
 * Admin-only route guard. Nests inside RequireAuth, so the session is already
 * resolved by the time this runs; it only checks the role. Members hitting an
 * admin URL directly are redirected to /overview (the backend's require_admin
 * dependency is the real wall — this is just UX).
 */
export const RequireAdmin = () => {
	const { isAdmin, loading } = useAuth();

	if (loading)
		return <Loading label="Checking session…" className="h-screen" />;
	if (!isAdmin) return <Navigate to="/overview" replace />;
	return <Outlet />;
};
