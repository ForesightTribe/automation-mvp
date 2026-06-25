import { useQuery } from "@tanstack/react-query";
import { useClient } from "../../context/ClientContext";
import { useDateRange } from "../../context/DateRangeContext";
import { useMarketplaces } from "../../context/MarketplaceContext";
import {
	getOverview,
	getTrends,
	getRevenue,
	getTopSkus,
	getSalesByCity,
	getSalesByCategory,
	getCategoryTrend,
	getCityCategory,
} from "./api";

/**
 * Data hooks for Sales & Analytics. Every query key includes the active client,
 * the global date range, and the marketplace selection, so changing any Navbar
 * control auto-refetches (Context holds the selection, React Query the data).
 * `enabled` guards against firing before a client is chosen. All endpoints share
 * the same {start, end, marketplaces} contract via PeriodDep.
 */
const useWindowed = (key, fetcher, extra) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	return useQuery({
		queryKey: [key, activeClientId, range, selected, extra],
		queryFn: () =>
			fetcher(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
				...extra,
			}),
		enabled: Boolean(activeClientId),
	});
};

export const useAnalyticsOverview = () =>
	useWindowed("analytics-overview", getOverview);

/** Daily ad+sales series — feeds the KPI sparklines (deduped with any other use). */
export const useAnalyticsTrends = () =>
	useWindowed("analytics-trends", getTrends);

export const useRevenue = () => useWindowed("analytics-revenue", getRevenue);

export const useTopSkus = (limit = 10) =>
	useWindowed("analytics-top-skus", getTopSkus, { limit });

export const useSalesByCity = () =>
	useWindowed("analytics-sales-by-city", getSalesByCity);

export const useSalesByCategory = () =>
	useWindowed("analytics-sales-by-category", getSalesByCategory);

export const useCategoryTrend = () =>
	useWindowed("analytics-category-trend", getCategoryTrend);

export const useCityCategory = (limit = 12) =>
	useWindowed("analytics-city-category", getCityCategory, { limit });
