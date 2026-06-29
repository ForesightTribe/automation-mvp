import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useClient } from "../../context/ClientContext";
import { useDateRange } from "../../context/DateRangeContext";
import { useMarketplaces } from "../../context/MarketplaceContext";
import {
	getSummary,
	getPerformance,
	getBudgetSplit,
	getCampaigns,
	getKeywords,
	getSov,
	getMarketplaceBreakdown,
	getVisibilityPlans,
	getCollections,
} from "./api";

/**
 * Data hooks for the Ads page. Every key includes the active client + global date
 * range + marketplace selection so the Navbar controls auto-refetch (Context holds
 * the selection, React Query the data). Snapshot reads (keywords, plans,
 * collections) drop the date range from their key since they aren't windowed.
 */
export const useAdsSummary = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	return useQuery({
		queryKey: ["ads-summary", activeClientId, range, selected],
		queryFn: () =>
			getSummary(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
			}),
		enabled: Boolean(activeClientId),
	});
};

/** Daily spend/impressions/ad_sales/roas — feeds the trend chart AND the KPI
 * sparklines (React Query dedupes the shared call). */
export const useAdsPerformance = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	return useQuery({
		queryKey: ["ads-performance", activeClientId, range, selected],
		queryFn: () =>
			getPerformance(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
			}),
		enabled: Boolean(activeClientId),
	});
};

export const useBudgetSplit = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	return useQuery({
		queryKey: ["ads-budget-split", activeClientId, range, selected],
		queryFn: () =>
			getBudgetSplit(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
			}),
		enabled: Boolean(activeClientId),
	});
};

export const useCampaigns = ({ page, limit = 20, status, sort, order }) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	return useQuery({
		queryKey: [
			"ads-campaigns",
			activeClientId,
			range,
			selected,
			page,
			limit,
			status,
			sort,
			order,
		],
		queryFn: () =>
			getCampaigns(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
				page,
				limit,
				status,
				sort,
				order,
			}),
		enabled: Boolean(activeClientId),
		placeholderData: keepPreviousData,
	});
};

/** Keyword/asset performance from the latest detail snapshot — not date-windowed,
 * so the key omits the range. */
export const useKeywords = ({
	page,
	limit = 20,
	campaignId,
	targetType,
	sort,
	order,
}) => {
	const { activeClientId } = useClient();
	const { selected } = useMarketplaces();
	return useQuery({
		queryKey: [
			"ads-keywords",
			activeClientId,
			selected,
			page,
			limit,
			campaignId,
			targetType,
			sort,
			order,
		],
		queryFn: () =>
			getKeywords(activeClientId, {
				marketplaces: selected,
				page,
				limit,
				campaignId,
				targetType,
				sort,
				order,
			}),
		enabled: Boolean(activeClientId),
		placeholderData: keepPreviousData,
	});
};

export const useSov = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	return useQuery({
		queryKey: ["ads-sov", activeClientId, range, selected],
		queryFn: () =>
			getSov(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
			}),
		enabled: Boolean(activeClientId),
	});
};

/** Per-marketplace ad breakdown. Keyed on client + date range only (not the
 * selection) — it returns a row for every marketplace and the page filters to the
 * selected/unconnected ones, mirroring the Overview breakdown. */
export const useAdMarketplaces = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	return useQuery({
		queryKey: ["ads-marketplaces", activeClientId, range],
		queryFn: () =>
			getMarketplaceBreakdown(activeClientId, {
				start: range.from,
				end: range.to,
			}),
		enabled: Boolean(activeClientId),
	});
};

export const useVisibilityPlans = () => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: ["ads-visibility-plans", activeClientId],
		queryFn: () => getVisibilityPlans(activeClientId),
		enabled: Boolean(activeClientId),
	});
};

export const useCollections = () => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: ["ads-collections", activeClientId],
		queryFn: () => getCollections(activeClientId),
		enabled: Boolean(activeClientId),
	});
};
