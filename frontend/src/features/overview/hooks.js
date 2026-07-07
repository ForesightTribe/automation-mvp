import { useQuery } from "@tanstack/react-query";
import { useClient } from "../../context/ClientContext";
import { useDateRange } from "../../context/DateRangeContext";
import { useMarketplaces } from "../../context/MarketplaceContext";
import {
	getOverview,
	getMarketplaceBreakdown,
	getRevenue,
	getTrends,
	getMonthlyTrends,
	getFreshness,
	getAlerts,
	getPublicShelf,
} from "./api";

/** Default month lookback for the Overview Operations charts. */
const MONTHLY_LOOKBACK = 3;

/**
 * Data hooks for the Overview page. The queryKey includes the active clientId,
 * the global date range, and the marketplace selection, so changing any of them
 * in the Navbar auto-refetches. `enabled` guards against firing before a client
 * is selected. staleTime is inherited from the global QueryClient default.
 */
export const useOverview = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	return useQuery({
		queryKey: ["overview", activeClientId, range, selected],
		queryFn: () =>
			getOverview(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
			}),
		enabled: Boolean(activeClientId),
	});
};

/**
 * Per-marketplace breakdown. Keyed on client + date range only (not the selection)
 * — the endpoint returns a row for every marketplace and the page filters to the
 * selected/unconnected ones, so the selection doesn't need to refetch.
 */
export const useMarketplaceBreakdown = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	return useQuery({
		queryKey: ["overview-marketplaces", activeClientId, range],
		queryFn: () =>
			getMarketplaceBreakdown(activeClientId, {
				start: range.from,
				end: range.to,
			}),
		enabled: Boolean(activeClientId),
	});
};

/** Revenue/units time series, keyed on client + date range + marketplace. */
export const useRevenue = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	return useQuery({
		queryKey: ["overview-revenue", activeClientId, range, selected],
		queryFn: () =>
			getRevenue(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
			}),
		enabled: Boolean(activeClientId),
	});
};

/**
 * Unified daily trend series (ad + sales) for the charts AND the KPI sparklines.
 * React Query dedupes by this key, so the KPI strip and both charts all share a
 * single request. Keyed on client + date range + marketplace.
 */
export const useTrends = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	return useQuery({
		queryKey: ["overview-trends", activeClientId, range, selected],
		queryFn: () =>
			getTrends(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
			}),
		enabled: Boolean(activeClientId),
	});
};

/**
 * Month-on-month operations trends (OSA, fill rate, PO value). Tenant-wide and
 * independent of the day-range / marketplace pickers — a fixed monthly lookback.
 * Shared by all three Operations charts (React Query dedupes to one request).
 */
export const useMonthlyTrends = () => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: ["overview-monthly-trends", activeClientId, MONTHLY_LOOKBACK],
		queryFn: () =>
			getMonthlyTrends(activeClientId, { months: MONTHLY_LOOKBACK }),
		enabled: Boolean(activeClientId),
	});
};

/** Data-freshness chips — client-scoped, independent of date/marketplace. */
export const useFreshness = () => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: ["overview-freshness", activeClientId],
		queryFn: () => getFreshness(activeClientId),
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

/** Public on-shelf distribution summary — weekly, so keyed on client + `days`. */
export const usePublicShelf = () => {
	const { activeClientId } = useClient();
	const { days } = useDateRange();
	return useQuery({
		queryKey: ["overview-public-shelf", activeClientId, days],
		queryFn: () => getPublicShelf(activeClientId, { days }),
		enabled: Boolean(activeClientId),
	});
};
