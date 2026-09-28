import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useClient } from "../../context/ClientContext";
import { useMarketplaces } from "../../context/MarketplaceContext";
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
 * (a `from_date_ist`) instead of the global date range. Changing the week in the
 * page's WeekPicker re-keys every dependent query and refetches. The week list
 * itself isn't week-scoped.
 */

/**
 * Resolves the global marketplace pill selection down to what the scorecard
 * endpoints actually accept: undefined (backend auto-detect) or exactly one
 * slug. Scorecard has no "blended" concept — `scorecard_service._platform`
 * always answers with a single platform — so a multi-select or "All" state
 * from the navbar pills can't map onto more than "let the backend choose".
 * Only when the picker narrows to ONE marketplace does that become explicit.
 */
const useScorecardMarketplace = () => {
	const { selected, allSelected } = useMarketplaces();
	if (allSelected || selected.length !== 1) return undefined;
	return selected[0];
};

export const useScorecardWeeks = () => {
	const { activeClientId } = useClient();
	const marketplace = useScorecardMarketplace();
	return useQuery({
		queryKey: ["scorecard-weeks", activeClientId, marketplace],
		queryFn: () => getWeeks(activeClientId, { marketplace }),
		enabled: Boolean(activeClientId),
	});
};

export const useScorecardWeekly = (from) => {
	const { activeClientId } = useClient();
	const marketplace = useScorecardMarketplace();
	return useQuery({
		queryKey: ["scorecard-weekly", activeClientId, from, marketplace],
		queryFn: () => getWeekly(activeClientId, { from, marketplace }),
		enabled: Boolean(activeClientId),
		placeholderData: keepPreviousData,
	});
};

export const useScorecardTrend = (weeks = 12) => {
	const { activeClientId } = useClient();
	const marketplace = useScorecardMarketplace();
	return useQuery({
		queryKey: ["scorecard-trend", activeClientId, weeks, marketplace],
		queryFn: () => getTrend(activeClientId, { weeks, marketplace }),
		enabled: Boolean(activeClientId),
	});
};

export const useKeySkus = ({ from, page, limit = 20 }) => {
	const { activeClientId } = useClient();
	const marketplace = useScorecardMarketplace();
	return useQuery({
		queryKey: ["scorecard-key-skus", activeClientId, from, page, limit, marketplace],
		queryFn: () => getKeySkus(activeClientId, { from, page, limit, marketplace }),
		enabled: Boolean(activeClientId),
		placeholderData: keepPreviousData,
	});
};

export const useFacilities = ({ from, page, limit = 20 }) => {
	const { activeClientId } = useClient();
	const marketplace = useScorecardMarketplace();
	return useQuery({
		queryKey: ["scorecard-facilities", activeClientId, from, page, limit, marketplace],
		queryFn: () => getFacilities(activeClientId, { from, page, limit, marketplace }),
		enabled: Boolean(activeClientId),
		placeholderData: keepPreviousData,
	});
};

/** POs behind a facility's fill loss — fetched lazily when a row is expanded
 * (gated by `enabled`), so the table only pulls drill-down data on demand. */
export const useFacilityPos = (facilityId, { page, limit = 10, enabled }) => {
	const { activeClientId } = useClient();
	const marketplace = useScorecardMarketplace();
	return useQuery({
		queryKey: [
			"scorecard-facility-pos", activeClientId, facilityId, page, limit, marketplace,
		],
		queryFn: () =>
			getFacilityPos(activeClientId, facilityId, { page, limit, marketplace }),
		enabled: Boolean(activeClientId) && Boolean(facilityId) && enabled,
		placeholderData: keepPreviousData,
	});
};
