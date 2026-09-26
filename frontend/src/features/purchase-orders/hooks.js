import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useClient } from "../../context/ClientContext";
import { useDateRange } from "../../context/DateRangeContext";
import { useMarketplaces } from "../../context/MarketplaceContext";
import {
	getPoSummary,
	getPoInsights,
	getPoSkus,
	getPoFile,
	getPo,
} from "./api";
import { downloadBlob } from "../../lib/exportTable";

/**
 * Resolves the global marketplace pill selection down to what the PO
 * endpoints actually accept: undefined (Blinkit, the only marketplace this
 * page had until now) or exactly "instamart" — never auto-detected, and
 * there's no blended PO view across marketplaces, so "All" or a multi-select
 * also falls back to undefined (Blinkit). Same convention as the Scorecard
 * page's `useScorecardMarketplace`.
 */
const usePoMarketplace = () => {
	const { selected, allSelected } = useMarketplaces();
	if (allSelected || selected.length !== 1 || selected[0] === "blinkit") {
		return undefined;
	}
	return selected[0];
};

/** The KPI tiles: ordered value, fill rate, undelivered value. */
export const usePoSummary = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const marketplace = usePoMarketplace();
	return useQuery({
		queryKey: ["po-summary", activeClientId, range, marketplace],
		queryFn: () =>
			getPoSummary(activeClientId, { start: range.from, end: range.to, marketplace }),
		enabled: Boolean(activeClientId),
	});
};

/** The PO table. Keeps the previous page on screen while the next one loads. */
export const usePoInsights = ({ scope, search, status, page }) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const marketplace = usePoMarketplace();
	return useQuery({
		queryKey: [
			"po-insights",
			activeClientId,
			range,
			scope,
			search,
			status,
			page,
			marketplace,
		],
		queryFn: () =>
			getPoInsights(activeClientId, {
				start: range.from,
				end: range.to,
				scope,
				search,
				status,
				page,
				marketplace,
			}),
		enabled: Boolean(activeClientId),
		placeholderData: keepPreviousData,
	});
};

/** The same shortfall per SKU rather than per PO. */
export const usePoSkus = ({ search, page }) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const marketplace = usePoMarketplace();
	return useQuery({
		queryKey: ["po-skus", activeClientId, range, search, page, marketplace],
		queryFn: () =>
			getPoSkus(activeClientId, {
				start: range.from,
				end: range.to,
				search,
				page,
				marketplace,
			}),
		enabled: Boolean(activeClientId),
		placeholderData: keepPreviousData,
	});
};

/** Download the section as a workbook. Reports its own busy/error state. */
export const usePoExport = (scope, status) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const marketplace = usePoMarketplace();
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState(null);

	const run = async () => {
		setBusy(true);
		setError(null);
		try {
			const blob = await getPoFile(activeClientId, {
				start: range.from,
				end: range.to,
				scope,
				status,
				marketplace,
			});
			downloadBlob(
				blob,
				`Purchase_Orders_${range.from}_to_${range.to}.xlsx`,
			);
		} catch (err) {
			setError(err.message);
		} finally {
			setBusy(false);
		}
	};

	return { run, busy, error };
};

/** One PO's full record, fetched when its row is opened. */
export const usePo = (poNumber) => {
	const { activeClientId } = useClient();
	const marketplace = usePoMarketplace();
	return useQuery({
		queryKey: ["po-detail", activeClientId, poNumber, marketplace],
		queryFn: () => getPo(activeClientId, poNumber, { marketplace }),
		enabled: Boolean(activeClientId && poNumber),
	});
};
