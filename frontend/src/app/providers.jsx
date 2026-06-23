import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "./queryClient";
import { AuthProvider } from "../context/AuthContext";
import { ClientProvider } from "../context/ClientContext";
import { DateRangeProvider } from "../context/DateRangeContext";

/**
 * Composes every global provider in one place, outermost first:
 *   QueryClient (server-state cache)
 *     -> Auth (token + user)
 *       -> Client (active client; uses React Query to load the list)
 *         -> DateRange (global `?days=` window)
 * App.jsx just renders <Providers><Router/></Providers>.
 */
export const Providers = ({ children }) => {
	return (
		<QueryClientProvider client={queryClient}>
			<AuthProvider>
				<ClientProvider>
					<DateRangeProvider>{children}</DateRangeProvider>
				</ClientProvider>
			</AuthProvider>
		</QueryClientProvider>
	);
};
