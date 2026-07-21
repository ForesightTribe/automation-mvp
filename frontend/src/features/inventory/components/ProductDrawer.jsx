import { useMemo, useState } from "react";
import { useProductStores } from "../hooks";
import { Drawer, DrawerStat, AvailabilityPill } from "../../../components/ui/Drawer";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { formatCurrency, formatNumber } from "../../../lib/format";

/** Worst first: out of stock, then not carried, then in stock. */
const rankOf = (s) => (s.listed && !s.in_stock ? 0 : !s.listed ? 1 : 2);

/**
 * One product across every store, in the slide-over — the mirror of StoreDrawer.
 *
 * Answers "where is this product weak?": the stores where it is out of stock, the
 * ones that don't carry it at all (a listing opportunity), and where it's fine. Same
 * shell, same worst-first sort and filter as the store drawer, so the two read the
 * same way. Only mounts when a product is selected.
 */
export const ProductDrawer = ({ productId, kind = "main", onClose }) => {
	const { data, isLoading, error, refetch } = useProductStores(productId, kind);
	const [q, setQ] = useState("");

	const stores = data?.stores ?? [];
	const oos = stores.filter((s) => s.listed && !s.in_stock);
	const absent = stores.filter((s) => !s.listed);

	const shown = useMemo(() => {
		const needle = q.trim().toLowerCase();
		return [...stores]
			.filter(
				(s) =>
					!needle ||
					(s.store_name || "").toLowerCase().includes(needle) ||
					(s.city || "").toLowerCase().includes(needle),
			)
			.sort(
				(a, b) =>
					rankOf(a) - rankOf(b) ||
					(a.city || "").localeCompare(b.city || "") ||
					(a.store_name || "").localeCompare(b.store_name || ""),
			);
	}, [stores, q]);

	return (
		<Drawer
			open={Boolean(productId)}
			onClose={onClose}
			title={data?.product_name || "Product"}
			subtitle={
				data
					? `Listed in ${formatNumber(data.stores_listed)} of ${formatNumber(data.stores_scraped)} stores`
					: undefined
			}
			stats={
				!isLoading &&
				!error && (
					<>
						<DrawerStat label="In stock" value={formatNumber(data?.stores_in_stock ?? 0)} tone="success" />
						<DrawerStat label="Out of stock" value={formatNumber(oos.length)} tone={oos.length ? "danger" : undefined} />
						<DrawerStat label="Not carried" value={formatNumber(absent.length)} tone={absent.length ? "warning" : undefined} />
					</>
				)
			}
		>
			{isLoading ? (
				<Loading label="Loading product…" />
			) : error ? (
				<ErrorState message={error.message} onRetry={refetch} />
			) : (
				<>
					{stores.length > 8 && (
						<input
							value={q}
							onChange={(e) => setQ(e.target.value)}
							placeholder="Filter by store or city…"
							className="mb-4 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-content placeholder:text-content-subtle focus:border-brand focus:outline-none"
						/>
					)}
					<table className="w-full border-collapse text-sm">
						<thead>
							<tr className="border-b border-border text-left text-content-subtle">
								<th className="py-2 font-medium">Store</th>
								<th className="py-2 font-medium">City</th>
								<th className="py-2 text-right font-medium">Units left</th>
								<th className="py-2 text-right font-medium">Status</th>
							</tr>
						</thead>
						<tbody>
							{shown.map((s) => (
								<tr key={s.merchant_id} className="border-b border-border/60">
									<td className="py-2.5 pr-3 text-content">
										{s.store_name || `Store ${s.merchant_id}`}
										{s.store_name && (
											<span className="ml-2 text-xs text-content-subtle">#{s.merchant_id}</span>
										)}
									</td>
									<td className="py-2.5 pr-3 capitalize text-content-muted">
										{s.city || "—"}
									</td>
									<td className="py-2.5 text-right tabular-nums text-content-muted">
										{s.listed ? formatNumber(s.inventory ?? 0) : "—"}
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
