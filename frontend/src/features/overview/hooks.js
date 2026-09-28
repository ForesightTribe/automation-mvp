import { useQuery } from "@tanstack/react-query";
import { useClient } from "../../context/ClientContext";
import { useDateRange } from "../../context/DateRangeContext";
import { toISODate } from "../../lib/dates";
import { useMarketplaces } from "../../context/MarketplaceContext";
import {
	getOverview,
	getMarketplaceBreakdown,
	getMarketplaceTrends,
	getRevenue,
	getTrends,
	getFreshness,
	getInsights,
	getCampaigns,
	getAvailabilityHistory,
	getPoSummary,
	getPoByMarketplace,
	getShareOfVoice,
	getTopCompetitors,
	getTopCompetitorsByMarketplace,
	getPricePosition,
	getDistribution,
	getDistributionByMarketplace,
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
	const { selected } = useMarketplaces();
	return useQuery({
		queryKey: ["overview-marketplaces", activeClientId, range],
		queryFn: () =>
			getMarketplaceBreakdown(activeClientId, {
				start: range.from,
				end: range.to,
			}),
		// The endpoint answers for the whole tenant and takes no marketplace
		// argument, so the picker is applied to the rows it returns. One cached
		// response serves every selection.
		select: (rows) =>
			selected ? rows.filter((m) => selected.includes(m.slug)) : rows,
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
/**
 * Daily revenue per marketplace over the selected window.
 *
 * Follows the date picker and the marketplace picker, the same as `useTrends`
 * beside it — the two are drawn on one chart and must cover the same days.
 */
export const useMarketplaceTrends = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	return useQuery({
		queryKey: [
			"overview-marketplace-trends",
			activeClientId,
			range,
			selected,
		],
		queryFn: () =>
			getMarketplaceTrends(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
			}),
		enabled: Boolean(activeClientId),
	});
};

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

/** Data-freshness chips — client-scoped, independent of date/marketplace. */
export const useFreshness = () => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: ["overview-freshness", activeClientId],
		queryFn: () => getFreshness(activeClientId),
		enabled: Boolean(activeClientId),
	});
};

/** Trailing daily series, independent of the picker: "yesterday" must not change
 *  because someone left the range on 90 days. */
const RECENT_DAYS = 15;

export const useRecentDays = () => {
	const { activeClientId } = useClient();
	const { selected } = useMarketplaces();
	const to = new Date();
	const from = new Date();
	from.setDate(from.getDate() - (RECENT_DAYS - 1));
	const range = { from: toISODate(from), to: toISODate(to) };
	return useQuery({
		queryKey: ["overview-recent", activeClientId, range, selected],
		queryFn: () =>
			getTrends(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
			}),
		enabled: Boolean(activeClientId),
	});
};

/** How far back an attention item may look. A problem from six weeks ago is
 *  history, not something to act on this morning. */
const ATTENTION_DAYS = 7;

/**
 * Ranked insights over a FIXED recent window, not the date picker's. Widening
 * the range to 90 days would quietly turn "needs attention" into "everything
 * that ever went wrong", and the list is meant to be today's work.
 */
export const useInsights = () => {
	const { activeClientId } = useClient();
	const to = new Date();
	const from = new Date();
	from.setDate(from.getDate() - (ATTENTION_DAYS - 1));
	const range = { from: toISODate(from), to: toISODate(to) };
	return useQuery({
		queryKey: ["overview-insights", activeClientId, range],
		staleTime: INSIGHT_STALE,
		queryFn: () =>
			getInsights(activeClientId, { start: range.from, end: range.to }),
		enabled: Boolean(activeClientId),
	});
};

/** Weekly availability, for the week-on-week comparison on the KPI. */
export const useAvailabilityHistory = () => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: ["overview-availability-history", activeClientId],
		queryFn: () => getAvailabilityHistory(activeClientId, { weeks: 8 }),
		enabled: Boolean(activeClientId),
	});
};

/** Campaigns for ONE day — the same day the glance reads, not the picker's window. */
export const useTopCampaignsForDay = (day) => {
	const { activeClientId } = useClient();
	const { selected } = useMarketplaces();
	return useQuery({
		queryKey: ["overview-campaigns-day", activeClientId, day, selected],
		queryFn: () =>
			getCampaigns(activeClientId, {
				start: day,
				end: day,
				limit: 50,
				marketplaces: selected,
			}),
		enabled: Boolean(activeClientId) && Boolean(day),
	});
};

/** Top campaigns by attributed revenue over the selected window. */
export const useTopCampaigns = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	return useQuery({
		queryKey: ["overview-top-campaigns", activeClientId, range, selected],
		queryFn: () =>
			getCampaigns(activeClientId, {
				start: range.from,
				end: range.to,
				limit: 200,
				marketplaces: selected,
			}),
		enabled: Boolean(activeClientId),
	});
};

/**
 * How long a scraped read stays fresh.
 *
 * ⚠️ These four aggregate the scrape tables and are the expensive reads on this
 * page. The keyword scrape behind them lands days apart, so the global
 * 5-minute default refetches them far more often than the data can change.
 */
const SCRAPE_STALE = 12 * 60 * 60 * 1000; // keyword scrape — days apart
const DAILY_STALE = 6 * 60 * 60 * 1000; // own-SKU scrape — daily
const INSIGHT_STALE = 30 * 60 * 1000; // the bell, on every page

/** Purchase orders over the selected window. */
export const usePoSummary = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	return useQuery({
		queryKey: ["overview-po-summary", activeClientId, range],
		queryFn: () =>
			getPoSummary(activeClientId, {
				start: range.from,
				end: range.to,
			}),
		enabled: Boolean(activeClientId),
	});
};

/** Purchase orders per marketplace, for the channel table under the figures. */
export const usePoByMarketplace = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	return useQuery({
		queryKey: ["overview-po-marketplaces", activeClientId, range, selected],
		queryFn: () =>
			getPoByMarketplace(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
			}),
		enabled: Boolean(activeClientId),
	});
};

/** Share of voice over the selected window. */
export const useShareOfVoice = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	return useQuery({
		queryKey: ["overview-sov", activeClientId, range, selected],
		staleTime: SCRAPE_STALE,
		queryFn: () =>
			getShareOfVoice(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
			}),
		enabled: Boolean(activeClientId),
	});
};

/** The competitor leaderboard for the same window. */
export const useTopCompetitors = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	return useQuery({
		queryKey: ["overview-competitors", activeClientId, range],
		staleTime: SCRAPE_STALE,
		queryFn: () =>
			getTopCompetitors(activeClientId, {
				start: range.from,
				end: range.to,
				limit: 6,
			}),
		enabled: Boolean(activeClientId),
	});
};

/** The competitor leaderboard split by channel, for the Overview table. */
export const useTopCompetitorsByMarketplace = (limit = 12) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	return useQuery({
		queryKey: [
			"overview-competitors-marketplaces",
			activeClientId,
			range,
			selected,
			limit,
		],
		queryFn: () =>
			getTopCompetitorsByMarketplace(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
				limit,
			}),
		enabled: Boolean(activeClientId),
	});
};

/** Price position against competitors over the selected window. */
/** `byMarketplace` splits each band by the shelf it was seen on — a price band
 *  is per shelf, so the same keyword can sit above the set on one and below on
 *  another. */
export const usePricePosition = ({ byMarketplace = false } = {}) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	return useQuery({
		queryKey: [
			"overview-price-position",
			activeClientId,
			range,
			selected,
			byMarketplace,
		],
		staleTime: SCRAPE_STALE,
		queryFn: () =>
			getPricePosition(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
				byMarketplace,
			}),
		enabled: Boolean(activeClientId),
	});
};

/** Reach and in-stock rate per SKU over the selected window. */
export const useDistribution = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	return useQuery({
		queryKey: ["overview-distribution", activeClientId, range, selected],
		staleTime: DAILY_STALE,
		queryFn: () =>
			getDistribution(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
			}),
		enabled: Boolean(activeClientId),
	});
};

/** Reach per marketplace, for the channel table under the figures. */
export const useDistributionByMarketplace = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	return useQuery({
		queryKey: [
			"overview-reach-marketplaces",
			activeClientId,
			range,
			selected,
		],
		queryFn: () =>
			getDistributionByMarketplace(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
			}),
		enabled: Boolean(activeClientId),
	});
};

/**
 * Each marketplace's slice of ONE day — the same day the glance reads.
 *
 * Channels the tenant has no scrape for come back `connected: false` with null
 * metrics, so the caller can show only what exists rather than a row of blanks.
 */
export const useMarketplacesForDay = (day) => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: ["overview-marketplaces-day", activeClientId, day],
		queryFn: () =>
			getMarketplaceBreakdown(activeClientId, { start: day, end: day }),
		enabled: Boolean(activeClientId) && Boolean(day),
		staleTime: INSIGHT_STALE,
	});
};
