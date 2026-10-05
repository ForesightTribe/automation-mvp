import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useClient } from "../../context/ClientContext";
import { useDateRange } from "../../context/DateRangeContext";
import { useMarketplaces } from "../../context/MarketplaceContext";
import { CUSTOM_RANGE_KEY } from "../../lib/constants";
import { toISODate } from "../../lib/dates";
import {
	getCompetition,
	getMarketing,
	getRawAds,
	getSalesPivot,
	getWeekendPlanning,
} from "./api";

/**
 * Blinkit reports on a T-1 basis, so reports must not include today. The global
 * presets (7/30/90d) always end *today*, so for reports we shift the whole
 * window back one day — same length, ending yesterday. A *custom* range is used
 * exactly as the user picked it (they chose those dates deliberately). This is
 * scoped to reports only; the global picker and every other page are untouched.
 */
const shiftBack1 = (iso) => {
	const d = new Date(iso);
	d.setDate(d.getDate() - 1);
	return toISODate(d);
};

const reportWindow = (range, activePreset) =>
	activePreset === CUSTOM_RANGE_KEY
		? { start: range.from, end: range.to }
		: { start: shiftBack1(range.from), end: shiftBack1(range.to) };

/**
 * Sales-pivot data. Keyed on the active client + global date range + marketplace
 * selection + metric, so changing any Navbar selector (or the metric toggle)
 * auto-refetches — the same pattern every dashboard page follows. `enabled`
 * guards against firing before a client is selected.
 */
export const useSalesPivot = (metric) => {
	const { activeClientId } = useClient();
	const { range, activePreset } = useDateRange();
	const { selected, ready } = useMarketplaces();
	const { start, end } = reportWindow(range, activePreset);
	return useQuery({
		queryKey: [
			"reports-sales-pivot",
			activeClientId,
			start,
			end,
			selected,
			metric,
		],
		queryFn: () =>
			getSalesPivot(activeClientId, {
				start,
				end,
				marketplaces: selected,
				metric,
			}),
		enabled: Boolean(activeClientId) && ready,
	});
};

/** Daily ad ledger + footer totals. Keyed on client + date range + marketplace. */
export const useMarketing = () => {
	const { activeClientId } = useClient();
	const { range, activePreset } = useDateRange();
	const { selected, ready } = useMarketplaces();
	const { start, end } = reportWindow(range, activePreset);
	return useQuery({
		queryKey: ["reports-marketing", activeClientId, start, end, selected],
		queryFn: () =>
			getMarketing(activeClientId, {
				start,
				end,
				marketplaces: selected,
			}),
		enabled: Boolean(activeClientId) && ready,
	});
};

/** Own-vs-competitor pricing, grouped by marketplace + keyword. `kind` filters
 * combos. Keyed on client + date range + marketplace + kind. */
export const useCompetition = (kind) => {
	const { activeClientId } = useClient();
	const { range, activePreset } = useDateRange();
	const { selected, ready } = useMarketplaces();
	const { start, end } = reportWindow(range, activePreset);
	return useQuery({
		queryKey: [
			"reports-competition",
			activeClientId,
			start,
			end,
			selected,
			kind,
		],
		queryFn: () =>
			getCompetition(activeClientId, {
				start,
				end,
				marketplaces: selected,
				kind,
			}),
		enabled: Boolean(activeClientId) && ready,
	});
};

/** Campaign spend and return with each Fri–Sun weekend as its own column group.
 *  Keyed on client + window + marketplace, like every other report here. */
export const useWeekendPlanning = () => {
	const { activeClientId } = useClient();
	const { range, activePreset } = useDateRange();
	const { selected, ready } = useMarketplaces();
	const { start, end } = reportWindow(range, activePreset);
	return useQuery({
		queryKey: [
			"reports-weekend-planning",
			activeClientId,
			start,
			end,
			selected,
		],
		queryFn: () =>
			getWeekendPlanning(activeClientId, {
				start,
				end,
				marketplaces: selected,
			}),
		enabled: Boolean(activeClientId) && ready,
	});
};

/**
 * A raw export sheet, one page at a time.
 *
 * `enabled` is passed by the caller so the rows are fetched only when that sheet
 * is actually opened: these run to tens of thousands of rows and nobody opens
 * the report to look at them first.
 */
export const useRawAds = (campaignType, page, enabled, marketplace = "blinkit") => {
	const { activeClientId } = useClient();
	const { range, activePreset } = useDateRange();
	const { start, end } = reportWindow(range, activePreset);
	return useQuery({
		queryKey: [
			"reports-raw-ads",
			activeClientId,
			start,
			end,
			marketplace,
			campaignType,
			page,
		],
		queryFn: () =>
			getRawAds(activeClientId, {
				start,
				end,
				marketplace,
				campaignType,
				page,
				limit: 100,
			}),
		enabled: Boolean(activeClientId && enabled),
		placeholderData: keepPreviousData,
	});
};
