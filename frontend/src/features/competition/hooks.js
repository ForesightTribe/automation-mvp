import { useQuery } from "@tanstack/react-query";
import { useClient } from "../../context/ClientContext";
import { useDateRange } from "../../context/DateRangeContext";
import {
	getShareOfVoice,
	getRankMatrix,
	getTopCompetitors,
	getPricePosition,
} from "./api";

/**
 * Data hooks for the Competition page. Every key includes the active client + the
 * global window's `days`, so the Navbar date picker and client switcher auto-refetch
 * (Context holds the selection, React Query the data). The public scrapes are weekly,
 * so `days` from the range maps to ~n weekly points (30d ≈ 4 weeks, 90d ≈ 12).
 */
export const useShareOfVoice = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	return useQuery({
		queryKey: ["comp-sov", activeClientId, range],
		queryFn: () => getShareOfVoice(activeClientId, { start: range.from, end: range.to }),
		enabled: Boolean(activeClientId),
	});
};

export const useRankMatrix = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	return useQuery({
		queryKey: ["comp-rank-matrix", activeClientId, range],
		queryFn: () => getRankMatrix(activeClientId, { start: range.from, end: range.to }),
		enabled: Boolean(activeClientId),
	});
};

export const useTopCompetitors = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	return useQuery({
		queryKey: ["comp-top", activeClientId, range],
		queryFn: () => getTopCompetitors(activeClientId, { start: range.from, end: range.to }),
		enabled: Boolean(activeClientId),
	});
};

export const usePricePosition = (kind = "main") => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	return useQuery({
		queryKey: ["comp-price", activeClientId, range, kind],
		queryFn: () => getPricePosition(activeClientId, { start: range.from, end: range.to, kind }),
		enabled: Boolean(activeClientId),
	});
};
