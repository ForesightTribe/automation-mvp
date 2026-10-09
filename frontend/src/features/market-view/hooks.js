import { useQuery } from "@tanstack/react-query";
import { useClient } from "../../context/ClientContext";
import { useDateRange } from "../../context/DateRangeContext";
import { useMarketplaces } from "../../context/MarketplaceContext";
import { useMarketView } from "./viewContext";
import {
	getKeywordPresence,
	getSkuVariance,
	getStoreCompetition,
	getBrandComparison,
} from "./api";

/**
 * Every read takes the active client, the global window and the marketplace
 * selection, plus the page's own city. `withKeyword` adds the selected keyword
 * for the sections that drill into one — the visibility table deliberately
 * does NOT, since it is the thing you pick the keyword from.
 */
const useRead = (key, fetcher, { withKeyword = false, ...extra } = {}) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	const { city, keyword } = useMarketView();
	const kw = withKeyword ? keyword : null;
	return useQuery({
		queryKey: [key, activeClientId, range, selected, city, kw, extra],
		queryFn: () =>
			fetcher(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
				city: city ?? undefined,
				keyword: kw ?? undefined,
				...extra,
			}),
		enabled: Boolean(activeClientId),
	});
};

export const useKeywordPresence = () => useRead("mv-keywords", getKeywordPresence);
export const useSkuVariance = () =>
	useRead("mv-skus", getSkuVariance, { withKeyword: true });
export const useStoreExplorer = (limit = 300) =>
	useRead("mv-stores", getStoreCompetition, { withKeyword: true, limit });

/** Every brand on the selected shelf: price, rank, presence, discount. */
export const useBrandComparison = () =>
	useRead("mv-brands", getBrandComparison, { withKeyword: true });
