import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useClient } from "../../context/ClientContext";
import { useDateRange } from "../../context/DateRangeContext";
import {
	getDistribution,
	getAvailability,
	getAvailabilityHistory,
	getPricing,
	getStores,
	getCities,
	getActions,
	getStoreDetail,
	getProductStores,
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
	const { range } = useDateRange();
	return useQuery({
		queryKey: ["inv-distribution", activeClientId, range, kind],
		queryFn: () => getDistribution(activeClientId, { start: range.from, end: range.to, kind }),
		enabled: Boolean(activeClientId),
	});
};

export const useAvailability = ({ page, limit = 20, kind = "main" }) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	return useQuery({
		queryKey: ["inv-availability", activeClientId, range, kind, page, limit],
		queryFn: () => getAvailability(activeClientId, { start: range.from, end: range.to, kind, page, limit }),
		enabled: Boolean(activeClientId),
		placeholderData: keepPreviousData,
	});
};

export const useAvailabilityHistory = (kind = "main", weeks = 12) => {
	// A trend is history: it deliberately IGNORES the reporting window (a 2-day custom
	// range would leave nothing to plot) and always looks back `weeks`.
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: ["inv-availability-history", activeClientId, weeks, kind],
		queryFn: () => getAvailabilityHistory(activeClientId, { weeks, kind }),
		enabled: Boolean(activeClientId),
	});
};

export const usePricing = (kind = "main") => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	return useQuery({
		queryKey: ["inv-pricing", activeClientId, range, kind],
		queryFn: () => getPricing(activeClientId, { start: range.from, end: range.to, kind }),
		enabled: Boolean(activeClientId),
	});
};

/**
 * Store-grain hooks. Same keying rule as above (client + window + kind), plus the
 * view's own filters, so the client switcher and date picker refetch everything.
 */

export const useStores = ({ kind = "main", city, tier } = {}) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	return useQuery({
		queryKey: ["inv-stores", activeClientId, range, kind, city, tier],
		queryFn: () => getStores(activeClientId, { start: range.from, end: range.to, kind, city, tier }),
		enabled: Boolean(activeClientId),
	});
};

export const useCities = (kind = "main") => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	return useQuery({
		queryKey: ["inv-cities", activeClientId, range, kind],
		queryFn: () => getCities(activeClientId, { start: range.from, end: range.to, kind }),
		enabled: Boolean(activeClientId),
	});
};

export const useActions = ({ action = "oos", page = 1, limit = 20, kind = "main", city } = {}) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	return useQuery({
		queryKey: ["inv-actions", activeClientId, range, kind, action, city, page, limit],
		queryFn: () =>
			getActions(activeClientId, { action, start: range.from, end: range.to, kind, city, page, limit }),
		enabled: Boolean(activeClientId),
		placeholderData: keepPreviousData,
	});
};

/** Drives the store drawer — only fetches once a store is actually selected. */
export const useStoreDetail = (merchantId, kind = "main") => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	return useQuery({
		queryKey: ["inv-store-detail", activeClientId, merchantId, range, kind],
		queryFn: () => getStoreDetail(activeClientId, merchantId, { start: range.from, end: range.to, kind }),
		enabled: Boolean(activeClientId && merchantId),
	});
};

/** Drives the product drawer — disabled until a product is selected. */
export const useProductStores = (productId, kind = "main") => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	return useQuery({
		queryKey: ["inv-product-stores", activeClientId, productId, range, kind],
		queryFn: () => getProductStores(activeClientId, productId, { start: range.from, end: range.to, kind }),
		enabled: Boolean(activeClientId && productId),
	});
};
