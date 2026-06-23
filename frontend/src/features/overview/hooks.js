import { useQuery } from "@tanstack/react-query";
import { useClient } from "../../context/ClientContext";
import { useDateRange } from "../../context/DateRangeContext";
import { getOverview, getAlerts } from "./api";

/**
 * Data hooks for the Overview page. The queryKey includes the active clientId
 * and the global date range, so switching client OR changing the range in the
 * Navbar auto-refetches. `enabled` guards against firing before a client is
 * selected. staleTime is inherited from the global QueryClient default.
 */
export const useOverview = () => {
	const { activeClientId } = useClient();
	const { days } = useDateRange();
	return useQuery({
		queryKey: ["overview", activeClientId, days],
		queryFn: () => getOverview(activeClientId, { days }),
		enabled: Boolean(activeClientId),
	});
};

export const useAlerts = () => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: ["overview-alerts", activeClientId],
		queryFn: () => getAlerts(activeClientId),
		enabled: Boolean(activeClientId),
	});
};
