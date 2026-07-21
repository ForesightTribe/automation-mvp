import { useMemo, useState } from "react";
import { useStoreDetail } from "../hooks";
import { Drawer, DrawerStat, AvailabilityPill } from "../../../components/ui/Drawer";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { formatCurrency, formatNumber } from "../../../lib/format";

/** Worst first: out of stock, then not carried, then in stock. */
const rankOf = (s) => (s.listed && !s.in_stock ? 0 : !s.listed ? 1 : 2);

/**
 * One dark store's whole shelf, in the slide-over.
 *
 * The detail layer: aggregates live in the tables, everything per-SKU lives here.
 * Crucially it lists SKUs the store does NOT carry (`listed: false`) next to the
 * stockouts — an absent product is invisible in a store's own data, so the range gap
 * only becomes actionable shown against the brand's active range.
 *
 * Rows are sorted worst-first and filterable by name, so a store with a long range
 * stays scannable. Only mounts when a store is selected; the hook is disabled until
 * then, so an unopened drawer costs nothing.
 */
export const StoreDrawer = ({ merchantId, kind = "main", onClose }) => {
	const { data, isLoading, error, refetch } = useStoreDetail(merchantId, kind);
	const [q, setQ] = useState("");

	const skus = data?.skus ?? [];
	const listed = skus.filter((s) => s.listed);
	const oos = listed.filter((s) => !s.in_stock);
	const absent = skus.filter((s) => !s.listed);

	const shown = useMemo(() => {
		const needle = q.trim().toLowerCase();
		return [...skus]
			.filter((s) => !needle || (s.product_name || "").toLowerCase().includes(needle))
			.sort((a, b) => rankOf(a) - rankOf(b) || (a.product_name || "").localeCompare(b.product_name || ""));
	}, [skus, q]);

	const subtitle = [
		data?.city,
		data?.merchant_type && data.merchant_type !== "express" ? "slower delivery" : null,
		`Store ${merchantId}`,
	]
		.filter(Boolean)
		.join(" · ");

	return (
		<Drawer
			open={Boolean(merchantId)}
			onClose={onClose}
			title={data?.store_name || `Store ${merchantId}`}
			subtitle={subtitle}
			stats={
				!isLoading &&
				!error && (
					<>
						<DrawerStat
							label="On shelf"
							value={`${formatNumber(listed.length)} / ${formatNumber(data?.active_range ?? 0)}`}
						/>
						<DrawerStat label="Out of stock" value={formatNumber(oos.length)} tone={oos.length ? "danger" : undefined} />
						<DrawerStat label="Not carried" value={formatNumber(absent.length)} tone={absent.length ? "warning" : undefined} />
					</>
				)
			}
		>
			{isLoading ? (
				<Loading label="Loading store…" />
			) : error ? (
				<ErrorState message={error.message} onRetry={refetch} />
			) : (
				<>
					{skus.length > 8 && (
						<input
							value={q}
							onChange={(e) => setQ(e.target.value)}
							placeholder="Filter products…"
							className="mb-4 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-content placeholder:text-content-subtle focus:border-brand focus:outline-none"
						/>
					)}
					<table className="w-full border-collapse text-sm">
						<thead>
							<tr className="border-b border-border text-left text-content-subtle">
								<th className="py-2 font-medium">Product</th>
								<th className="py-2 text-right font-medium">Units left</th>
								<th className="py-2 text-right font-medium">Price</th>
								<th className="py-2 text-right font-medium">Status</th>
							</tr>
						</thead>
						<tbody>
							{shown.map((s) => (
								<tr key={s.platform_product_id} className="border-b border-border/60">
									<td className="py-2.5 pr-3 text-content">
										{s.product_name || s.platform_product_id}
									</td>
									<td className="py-2.5 text-right tabular-nums text-content-muted">
										{s.listed ? formatNumber(s.inventory ?? 0) : "—"}
									</td>
									<td className="py-2.5 text-right tabular-nums text-content-muted">
										{s.price ? formatCurrency(s.price) : "—"}
									</td>
									<td className="py-2.5 text-right">
										<AvailabilityPill listed={s.listed} inStock={s.in_stock} />
									</td>
								</tr>
							))}
						</tbody>
					</table>
				</>
			)}
		</Drawer>
	);
};
