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
	getInstamartBudgetSplit,
	getInstamartProducts,
	getInstamartKeywords,
	getInstamartCampaignKeywords,
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
	const { selected, ready } = useMarketplaces();
	return useQuery({
		queryKey: ["ads-summary", activeClientId, range, selected],
		queryFn: () =>
			getSummary(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
			}),
		enabled: Boolean(activeClientId) && ready,
	});
};

export const useAdsPerformance = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected, ready } = useMarketplaces();
	return useQuery({
		queryKey: ["ads-performance", activeClientId, range, selected],
		queryFn: () =>
			getPerformance(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
			}),
		enabled: Boolean(activeClientId) && ready,
	});
};

export const useBudgetSplit = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected, ready } = useMarketplaces();
	return useQuery({
		queryKey: ["ads-budget-split", activeClientId, range, selected],
		queryFn: () =>
			getBudgetSplit(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
			}),
		enabled: Boolean(activeClientId) && ready,
	});
};

export const useCampaigns = ({ page, limit = 20, status, sort, order }) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected, ready } = useMarketplaces();
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
		enabled: Boolean(activeClientId) && ready,
		placeholderData: keepPreviousData,
	});
};

export const useKeywords = ({ page, limit = 20, campaignId, targetType, sort, order }) => {
	const { activeClientId } = useClient();
	const { selected, ready } = useMarketplaces();
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
		enabled: Boolean(activeClientId) && ready,
		placeholderData: keepPreviousData,
	});
};

export const useSov = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected, ready } = useMarketplaces();
	return useQuery({
		queryKey: ["ads-sov", activeClientId, range, selected],
		queryFn: () =>
			getSov(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
			}),
		enabled: Boolean(activeClientId) && ready,
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
 * Only fetched when Zepto is in scope — `selected` is the resolved selection, so
 * "All" lists every connected marketplace. Deliberately not merged into useKeywords —
 * that hook backs the Blinkit keywords table, whose row shape Zepto cannot
 * fill (no campaign id, no direct/indirect sales split).
 */
export const useZeptoKeywords = ({ sort = "spend", order = "desc", enabled = true } = {}) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected, ready } = useMarketplaces();
	const wantsZepto = selected.includes("zepto");
	return useQuery({
		queryKey: ["ads-zepto-keywords", activeClientId, range, sort, order],
		queryFn: () =>
			getZeptoKeywords(activeClientId, {
				start: range.from,
				end: range.to,
				sort,
				order,
			}),
		enabled: Boolean(activeClientId) && wantsZepto && enabled && ready,
		placeholderData: keepPreviousData,
	});
};

/** Zepto spend split by campaign type. Skipped when Zepto is out of scope. */
export const useZeptoBudgetSplit = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected, ready } = useMarketplaces();
	const wantsZepto = selected.includes("zepto");
	return useQuery({
		queryKey: ["ads-zepto-budget-split", activeClientId, range],
		queryFn: () =>
			getZeptoBudgetSplit(activeClientId, {
				start: range.from,
				end: range.to,
			}),
		enabled: Boolean(activeClientId) && wantsZepto && ready,
		placeholderData: keepPreviousData,
	});
};

/** Instamart spend split by campaign type, windowed by the date picker
 * (see api.js). Skipped when Instamart is out of scope. */
export const useInstamartBudgetSplit = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected, ready } = useMarketplaces();
	const wantsInstamart = selected.includes("instamart");
	return useQuery({
		queryKey: ["ads-instamart-budget-split", activeClientId, range],
		queryFn: () =>
			getInstamartBudgetSplit(activeClientId, {
				start: range.from,
				end: range.to,
			}),
		enabled: Boolean(activeClientId) && wantsInstamart && ready,
		placeholderData: keepPreviousData,
	});
};

/** Instamart ad performance per product, account-wide, each row's `campaigns`
 * breaking its total down by campaign. Skipped when Instamart is out of
 * scope. No ad-type filter — it existed earlier and was removed as
 * unreliable (see asset_metrics.py's docstring). */
export const useInstamartProducts = ({ enabled = true } = {}) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected, ready } = useMarketplaces();
	const wantsInstamart = selected.includes("instamart");
	return useQuery({
		queryKey: ["ads-instamart-products", activeClientId, range],
		queryFn: () =>
			getInstamartProducts(activeClientId, {
				start: range.from,
				end: range.to,
			}),
		enabled: Boolean(activeClientId) && wantsInstamart && enabled && ready,
		placeholderData: keepPreviousData,
	});
};

/** Instamart keyword performance, account-wide, same `campaigns` breakdown.
 * Skipped when Instamart is out of scope. */
export const useInstamartKeywords = ({
	sort = "spend",
	order = "desc",
	enabled = true,
} = {}) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected, ready } = useMarketplaces();
	const wantsInstamart = selected.includes("instamart");
	return useQuery({
		queryKey: ["ads-instamart-keywords", activeClientId, range, sort, order],
		queryFn: () =>
			getInstamartKeywords(activeClientId, {
				start: range.from,
				end: range.to,
				sort,
				order,
			}),
		enabled: Boolean(activeClientId) && wantsInstamart && enabled && ready,
		placeholderData: keepPreviousData,
	});
};

/** Top keywords by spend for ONE Instamart campaign, windowed — fills the
 * Campaign insights drawer's "Top keywords by spend" for an Instamart
 * campaign. `campaignId` is Instamart's UUID-string campaign id (distinct
 * from Blinkit/Zepto's integer ids — see CampaignRow's docstring), so the
 * caller decides which drawer data source to use by the id's shape. */
export const useInstamartCampaignKeywords = (campaignId, { enabled = true } = {}) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	return useQuery({
		queryKey: ["ads-instamart-campaign-keywords", activeClientId, campaignId, range],
		queryFn: () =>
			getInstamartCampaignKeywords(activeClientId, {
				campaignId,
				start: range.from,
				end: range.to,
				limit: 10,
			}),
		enabled: Boolean(activeClientId) && Boolean(campaignId) && enabled,
		placeholderData: keepPreviousData,
	});
};

/** Zepto share of voice per campaign. Skipped when Zepto is out of scope. */
export const useZeptoSov = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected, ready } = useMarketplaces();
	const wantsZepto = selected.includes("zepto");
	return useQuery({
		queryKey: ["ads-zepto-sov", activeClientId, range],
		queryFn: () =>
			getZeptoSov(activeClientId, { start: range.from, end: range.to }),
		enabled: Boolean(activeClientId) && wantsZepto && ready,
		placeholderData: keepPreviousData,
	});
};

/** Zepto ad performance per SKU. Skipped when Zepto is out of scope. */
export const useZeptoProducts = ({ campaignCategory = "", enabled = true } = {}) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected, ready } = useMarketplaces();
	const wantsZepto = selected.includes("zepto");
	return useQuery({
		queryKey: ["ads-zepto-products", activeClientId, range, campaignCategory],
		queryFn: () =>
			getZeptoProducts(activeClientId, {
				start: range.from,
				end: range.to,
				campaignCategory,
			}),
		enabled: Boolean(activeClientId) && wantsZepto && enabled && ready,
		placeholderData: keepPreviousData,
	});
};

/** Zepto ad performance for one breakdown dimension: category, city or page. */
export const useZeptoBreakdown = ({ dimension, campaignCategory = "", enabled = true } = {}) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected, ready } = useMarketplaces();
	const wantsZepto = selected.includes("zepto");
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
		enabled: Boolean(activeClientId) && wantsZepto && enabled && ready,
		placeholderData: keepPreviousData,
	});
};
