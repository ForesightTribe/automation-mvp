import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useClient } from "../../context/ClientContext";
import { useDateRange } from "../../context/DateRangeContext";
import { useMarketplaces } from "../../context/MarketplaceContext";
import {
	getProductDetail,
	getProductPos,
	getProducts,
	getProductPublic,
} from "./api";

/**
 * Data hooks for Products. Like the rest of the dashboard, every key includes the
 * active client + date range + marketplace selection so the Navbar controls
 * auto-refetch (Context holds the selection, React Query the data). The list also
 * keys on its filter/page state. `keepPreviousData` keeps the table populated
 * during page/sort/search changes so it doesn't flash empty.
 */
export const useProducts = ({ page, limit = 20, sort, status, search }) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	return useQuery({
		queryKey: [
			"products",
			activeClientId,
			range,
			selected,
			page,
			limit,
			sort,
			status,
			search,
		],
		queryFn: () =>
			getProducts(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
				page,
				limit,
				sort,
				sku_status: status || undefined,
				search: search || undefined,
			}),
		enabled: Boolean(activeClientId),
		placeholderData: keepPreviousData,
	});
};

export const useProductDetail = (itemId) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	return useQuery({
		queryKey: ["product-detail", activeClientId, itemId, range, selected],
		queryFn: () =>
			getProductDetail(activeClientId, itemId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
			}),
		enabled: Boolean(activeClientId && itemId),
	});
};

/** Public (scraped) view for one SKU — weekly data, so keyed on client + item +
 * the selected start/end window. */
export const useProductPublic = (itemId) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	return useQuery({
		queryKey: ["product-public", activeClientId, itemId, range],
		queryFn: () =>
			getProductPublic(activeClientId, itemId, { start: range.from, end: range.to }),
		enabled: Boolean(activeClientId && itemId),
	});
};

/** PO history is tenant-wide (not date-windowed) — keyed only on client + page. */
export const useProductPos = (itemId, page = 1, limit = 10) => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: ["product-pos", activeClientId, itemId, page, limit],
		queryFn: () => getProductPos(activeClientId, itemId, { page, limit }),
		enabled: Boolean(activeClientId && itemId),
		placeholderData: keepPreviousData,
	});
};
