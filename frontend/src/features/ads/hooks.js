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
	getZeptoKeywords,
	getZeptoBudgetSplit,
	getZeptoSov,
	getZeptoProducts,
	getZeptoBreakdown,
	getSov,
	getMarketplaceBreakdown,
	getVisibilityPlans,
	getCollections,
} from "./api";

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
		queryKey: ["ads-campaigns", activeClientId, range, selected, page, limit, status, sort, order],
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

export const useKeywords = ({ page, limit = 20, campaignId, targetType, sort, order }) => {
	const { activeClientId } = useClient();
	const { selected } = useMarketplaces();
	return useQuery({
		queryKey: ["ads-keywords", activeClientId, selected, page, limit, campaignId, targetType, sort, order],
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

/** Zepto keyword performance for the selected window.
 *
 * Only fetched when Zepto is in scope: an empty `selected` means "all
 * marketplaces", which includes it. Deliberately not merged into useKeywords —
 * that hook backs the Blinkit keywords table, whose row shape Zepto cannot
 * fill (no campaign id, no direct/indirect sales split).
 */
export const useZeptoKeywords = ({ sort = "spend", order = "desc", enabled = true } = {}) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	const wantsZepto = !selected?.length || selected.includes("zepto");
	return useQuery({
		queryKey: ["ads-zepto-keywords", activeClientId, range, sort, order],
		queryFn: () =>
			getZeptoKeywords(activeClientId, {
				start: range.from,
				end: range.to,
				sort,
				order,
			}),
		enabled: Boolean(activeClientId) && wantsZepto && enabled,
		placeholderData: keepPreviousData,
	});
};

/** Zepto spend split by campaign type. Skipped when Zepto is out of scope. */
export const useZeptoBudgetSplit = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	const wantsZepto = !selected?.length || selected.includes("zepto");
	return useQuery({
		queryKey: ["ads-zepto-budget-split", activeClientId, range],
		queryFn: () =>
			getZeptoBudgetSplit(activeClientId, {
				start: range.from,
				end: range.to,
			}),
		enabled: Boolean(activeClientId) && wantsZepto,
		placeholderData: keepPreviousData,
	});
};

/** Zepto share of voice per campaign. Skipped when Zepto is out of scope. */
export const useZeptoSov = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	const wantsZepto = !selected?.length || selected.includes("zepto");
	return useQuery({
		queryKey: ["ads-zepto-sov", activeClientId, range],
		queryFn: () =>
			getZeptoSov(activeClientId, { start: range.from, end: range.to }),
		enabled: Boolean(activeClientId) && wantsZepto,
		placeholderData: keepPreviousData,
	});
};

/** Zepto ad performance per SKU. Skipped when Zepto is out of scope. */
export const useZeptoProducts = ({ campaignCategory = "", enabled = true } = {}) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	const wantsZepto = !selected?.length || selected.includes("zepto");
	return useQuery({
		queryKey: ["ads-zepto-products", activeClientId, range, campaignCategory],
		queryFn: () =>
			getZeptoProducts(activeClientId, {
				start: range.from,
				end: range.to,
				campaignCategory,
			}),
		enabled: Boolean(activeClientId) && wantsZepto && enabled,
		placeholderData: keepPreviousData,
	});
};

/** Zepto ad performance for one breakdown dimension: category, city or page. */
export const useZeptoBreakdown = ({ dimension, campaignCategory = "", enabled = true } = {}) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	const wantsZepto = !selected?.length || selected.includes("zepto");
	return useQuery({
		queryKey: [
			"ads-zepto-breakdown",
			activeClientId,
			range,
			dimension,
			campaignCategory,
		],
		queryFn: () =>
			getZeptoBreakdown(activeClientId, {
				start: range.from,
				end: range.to,
				dimension,
				campaignCategory,
			}),
		enabled: Boolean(activeClientId) && wantsZepto && enabled,
		placeholderData: keepPreviousData,
	});
};
