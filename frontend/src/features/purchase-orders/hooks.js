import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useClient } from "../../context/ClientContext";
import { useDateRange } from "../../context/DateRangeContext";
import {
	getPoSummary,
	getPoInsights,
	getPoSkus,
	getPoFile,
	getPo,
} from "./api";
import { downloadBlob } from "../../lib/exportTable";

/** The KPI tiles: ordered value, fill rate, undelivered value. */
export const usePoSummary = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	return useQuery({
		queryKey: ["po-summary", activeClientId, range],
		queryFn: () =>
			getPoSummary(activeClientId, { start: range.from, end: range.to }),
		enabled: Boolean(activeClientId),
	});
};

/** The PO table. Keeps the previous page on screen while the next one loads. */
export const usePoInsights = ({ scope, search, status, page }) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	return useQuery({
		queryKey: [
			"po-insights",
			activeClientId,
			range,
			scope,
			search,
			status,
			page,
		],
		queryFn: () =>
			getPoInsights(activeClientId, {
				start: range.from,
				end: range.to,
				scope,
				search,
				status,
				page,
			}),
		enabled: Boolean(activeClientId),
		placeholderData: keepPreviousData,
	});
};

/** The same shortfall per SKU rather than per PO. */
export const usePoSkus = ({ search, page }) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	return useQuery({
		queryKey: ["po-skus", activeClientId, range, search, page],
		queryFn: () =>
			getPoSkus(activeClientId, {
				start: range.from,
				end: range.to,
				search,
				page,
			}),
		enabled: Boolean(activeClientId),
		placeholderData: keepPreviousData,
	});
};

/** Download the section as a workbook. Reports its own busy/error state. */
export const usePoExport = (scope, status) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
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
	return useQuery({
		queryKey: ["po-detail", activeClientId, poNumber],
		queryFn: () => getPo(activeClientId, poNumber),
		enabled: Boolean(activeClientId && poNumber),
	});
};
