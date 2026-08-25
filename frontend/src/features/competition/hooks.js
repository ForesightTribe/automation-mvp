import { useQuery } from "@tanstack/react-query";
import { useClient } from "../../context/ClientContext";
import { useDateRange } from "../../context/DateRangeContext";
import { useMarketplaces } from "../../context/MarketplaceContext";
import {
	getShareOfVoice,
	getRankMatrix,
	getTopCompetitors,
	getPricePosition,
} from "./api";

/**
 * Data hooks for the Competition page. Every key includes the active client + the
 * global window's `days` + the marketplace selection, so the Navbar date picker,
 * client switcher, and marketplace picker all auto-refetch (Context holds the
 * selection, React Query the data). The public scrapes are weekly, so `days` from
 * the range maps to ~n weekly points (30d ≈ 4 weeks, 90d ≈ 12).
 */
export const useShareOfVoice = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	return useQuery({
		queryKey: ["comp-sov", activeClientId, range, selected],
		queryFn: () =>
			getShareOfVoice(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
			}),
		enabled: Boolean(activeClientId),
	});
};

export const useRankMatrix = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	return useQuery({
		queryKey: ["comp-rank-matrix", activeClientId, range, selected],
		queryFn: () =>
			getRankMatrix(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
			}),
		enabled: Boolean(activeClientId),
	});
};

export const useTopCompetitors = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	return useQuery({
		queryKey: ["comp-top", activeClientId, range, selected],
		queryFn: () =>
			getTopCompetitors(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
			}),
		enabled: Boolean(activeClientId),
	});
};

export const usePricePosition = (kind = "main") => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	return useQuery({
		queryKey: ["comp-price", activeClientId, range, selected, kind],
		queryFn: () =>
			getPricePosition(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
				kind,
			}),
		enabled: Boolean(activeClientId),
	});
};
