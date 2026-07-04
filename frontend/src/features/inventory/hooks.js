import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useClient } from "../../context/ClientContext";
import { useDateRange } from "../../context/DateRangeContext";
import {
	getDistribution,
	getAvailability,
	getAvailabilityHistory,
	getPricing,
} from "./api";

/**
 * Data hooks for the Inventory page's public own-SKU surface. Keys include the
 * active client + the window's `days` + the `kind` filter (main | combo | all), so
 * the client switcher, date picker, and combo toggle all auto-refetch. Public
 * scrapes are weekly, so `days` maps to ~n weekly points. `/availability` is
 * paginated, so its hook also takes a page.
 */
export const useDistribution = (kind = "main") => {
	const { activeClientId } = useClient();
	const { days } = useDateRange();
	return useQuery({
		queryKey: ["inv-distribution", activeClientId, days, kind],
		queryFn: () => getDistribution(activeClientId, { days, kind }),
		enabled: Boolean(activeClientId),
	});
};

export const useAvailability = ({ page, limit = 20, kind = "main" }) => {
	const { activeClientId } = useClient();
	const { days } = useDateRange();
	return useQuery({
		queryKey: ["inv-availability", activeClientId, days, kind, page, limit],
		queryFn: () => getAvailability(activeClientId, { days, kind, page, limit }),
		enabled: Boolean(activeClientId),
		placeholderData: keepPreviousData,
	});
};

export const useAvailabilityHistory = (kind = "main") => {
	const { activeClientId } = useClient();
	const { days } = useDateRange();
	return useQuery({
		queryKey: ["inv-availability-history", activeClientId, days, kind],
		queryFn: () => getAvailabilityHistory(activeClientId, { days, kind }),
		enabled: Boolean(activeClientId),
	});
};

export const usePricing = (kind = "main") => {
	const { activeClientId } = useClient();
	const { days } = useDateRange();
	return useQuery({
		queryKey: ["inv-pricing", activeClientId, days, kind],
		queryFn: () => getPricing(activeClientId, { days, kind }),
		enabled: Boolean(activeClientId),
	});
};
