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
	getSkuPos,
} from "./api";
import { downloadBlob } from "../../lib/exportTable";

/**
 * The page's own single marketplace (`orders`, picked with the navbar pills on this
 * page), in the form the PO endpoints accept: undefined for Blinkit (their original
 * default), else "instamart" or "zepto".
 *
 * `ready` holds every query until the client's marketplace list has landed, so a
 * Zepto choice is not first fetched as Blinkit's orders and then swapped.
 */
const usePoMarketplace = () => {
	const { orders, ready } = useMarketplaces();
	return {
		marketplace: !orders || orders === "blinkit" ? undefined : orders,
		ready,
	};
};

/** The KPI tiles: ordered value, fill rate, undelivered value. */
export const usePoSummary = () => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { marketplace, ready } = usePoMarketplace();
	return useQuery({
		queryKey: ["po-summary", activeClientId, range, marketplace],
		queryFn: () =>
			getPoSummary(activeClientId, {
				start: range.from,
				end: range.to,
				marketplace,
			}),
		enabled: Boolean(activeClientId) && ready,
	});
};

/** The PO table. Keeps the previous page on screen while the next one loads. */
export const usePoInsights = ({ scope, search, status, page, sort, order }) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { marketplace, ready } = usePoMarketplace();
	return useQuery({
		queryKey: [
			"po-insights",
			activeClientId,
			range,
			scope,
			search,
			status,
			page,
			sort,
			order,
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
				sort,
				order,
				marketplace,
			}),
		enabled: Boolean(activeClientId) && ready,
		placeholderData: keepPreviousData,
	});
};

/** The same shortfall per SKU rather than per PO. */
export const usePoSkus = ({ search, page, sort, order }) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { marketplace, ready } = usePoMarketplace();
	return useQuery({
		queryKey: [
			"po-skus",
			activeClientId,
			range,
			search,
			page,
			marketplace,
			sort,
			order,
		],
		queryFn: () =>
			getPoSkus(activeClientId, {
				start: range.from,
				end: range.to,
				search,
				page,
				sort,
				order,
				marketplace,
			}),
		enabled: Boolean(activeClientId) && ready,
		placeholderData: keepPreviousData,
	});
};

/** Download the section as a workbook. Reports its own busy/error state. */
export const usePoExport = (scope, status) => {
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { marketplace } = usePoMarketplace();
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
	const { marketplace, ready } = usePoMarketplace();
	return useQuery({
		queryKey: ["po-detail", activeClientId, poNumber, marketplace],
		queryFn: () => getPo(activeClientId, poNumber, { marketplace }),
		enabled: Boolean(activeClientId && poNumber) && ready,
	});
};

/** Every PO carrying one SKU. Only fetched once a SKU is opened. */
export const useSkuPos = (itemId) => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: ["sku-pos", activeClientId, itemId],
		queryFn: () => getSkuPos(activeClientId, itemId),
		enabled: Boolean(activeClientId) && Boolean(itemId),
	});
};
