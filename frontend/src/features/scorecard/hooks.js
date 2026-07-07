import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useClient } from "../../context/ClientContext";
import {
	getWeeks,
	getWeekly,
	getTrend,
	getKeySkus,
	getFacilities,
	getFacilityPos,
} from "./api";

/**
 * Data hooks for the Scorecard page. Unlike the rest of the dashboard, scorecard
 * data is weekly snapshots — so these keys carry a page-local `selectedWeek`
 * (a `from_date_ist`) instead of the global date range / marketplace selection.
 * Changing the week in the page's WeekPicker re-keys every dependent query and
 * refetches. The week list itself isn't week-scoped.
 */
export const useScorecardWeeks = () => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: ["scorecard-weeks", activeClientId],
		queryFn: () => getWeeks(activeClientId),
		enabled: Boolean(activeClientId),
	});
};

export const useScorecardWeekly = (from) => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: ["scorecard-weekly", activeClientId, from],
		queryFn: () => getWeekly(activeClientId, { from }),
		enabled: Boolean(activeClientId),
		placeholderData: keepPreviousData,
	});
};

export const useScorecardTrend = (weeks = 12) => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: ["scorecard-trend", activeClientId, weeks],
		queryFn: () => getTrend(activeClientId, { weeks }),
		enabled: Boolean(activeClientId),
	});
};

export const useKeySkus = ({ from, page, limit = 20 }) => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: ["scorecard-key-skus", activeClientId, from, page, limit],
		queryFn: () => getKeySkus(activeClientId, { from, page, limit }),
		enabled: Boolean(activeClientId),
		placeholderData: keepPreviousData,
	});
};

export const useFacilities = ({ from, page, limit = 20 }) => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: ["scorecard-facilities", activeClientId, from, page, limit],
		queryFn: () => getFacilities(activeClientId, { from, page, limit }),
		enabled: Boolean(activeClientId),
		placeholderData: keepPreviousData,
	});
};

/** POs behind a facility's fill loss — fetched lazily when a row is expanded
 * (gated by `enabled`), so the table only pulls drill-down data on demand. */
export const useFacilityPos = (facilityId, { page, limit = 10, enabled }) => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: ["scorecard-facility-pos", activeClientId, facilityId, page, limit],
		queryFn: () => getFacilityPos(activeClientId, facilityId, { page, limit }),
		enabled: Boolean(activeClientId) && Boolean(facilityId) && enabled,
		placeholderData: keepPreviousData,
	});
};
