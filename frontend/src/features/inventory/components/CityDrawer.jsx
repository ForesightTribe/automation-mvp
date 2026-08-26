import { useMemo, useState } from "react";
import { useStores } from "../hooks";
import { Drawer, DrawerStat } from "../../../components/ui/Drawer";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { formatNumber } from "../../../lib/format";

const pct = (v) => (v === null || v === undefined ? "—" : `${Number(v).toFixed(1)}%`);
const stockClass = (v) =>
	v === null || v === undefined ? "text-content-subtle" : v < 90 ? "text-danger" : v < 97 ? "text-warning" : "text-content";

/**
 * All stores in one city, in the slide-over — so "By city" and "Worst locations"
 * open the same consistent detail panel as stores and products, instead of the
 * explorer navigating in place. Each store row opens the store drawer (`onSelectStore`),
 * so the drill continues city → store → shelf without leaving the overlay pattern.
 */
export const CityDrawer = ({ city, kind = "main", onClose, onSelectStore }) => {
	const { data, isLoading, error, refetch } = useStores({ kind, city });
	const [q, setQ] = useState("");

	const stores = data?.stores ?? [];
	const range = data?.active_range ?? 0;
	const oos = stores.reduce((a, s) => a + s.skus_out_of_stock, 0);
	const missing = stores.reduce((a, s) => a + s.skus_not_listed, 0);
	// Both readings, side by side — see AvailabilityExplorer for why neither replaces
	// the other.
	const shown = useMemo(() => {
		const needle = q.trim().toLowerCase();
		return [...stores]
			.filter((s) => !needle || (s.store_name || s.merchant_id).toLowerCase().includes(needle))
			.sort((a, b) => b.skus_out_of_stock - a.skus_out_of_stock || a.reach_pct - b.reach_pct);
	}, [stores, q]);

	return (
		<Drawer
			open={Boolean(city)}
			onClose={onClose}
			title={city ? city[0].toUpperCase() + city.slice(1) : ""}
			subtitle={data ? `${formatNumber(stores.length)} stores selling you here` : undefined}
			stats={
				!isLoading &&
				!error && (
					<>
						<DrawerStat
							label="Stores"
							value={formatNumber(stores.length)}
							hint="stocking you here"
						/>
						<DrawerStat
							label="Out of stock"
							value={formatNumber(oos)}
							hint="products on shelf but empty"
							tone={oos ? "danger" : undefined}
						/>
						<DrawerStat
							label="Missing listings"
							value={formatNumber(missing)}
							hint="products a store doesn't carry"
							tone={missing ? "warning" : undefined}
						/>
					</>
				)
			}
		>
			{isLoading ? (
				<Loading label="Loading city…" />
			) : error ? (
				<ErrorState message={error.message} onRetry={refetch} />
			) : (
				<>
					{stores.length > 8 && (
						<input
							value={q}
							onChange={(e) => setQ(e.target.value)}
							placeholder="Filter stores…"
							className="mb-4 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-content placeholder:text-content-subtle focus:border-brand focus:outline-none"
						/>
					)}
					<table className="w-full border-collapse text-sm">
						<thead>
							<tr className="border-b border-border text-left text-content-subtle">
								<th className="py-2 font-medium">Store</th>
								<th className="py-2 text-right font-medium">On shelf</th>
								<th className="py-2 text-right font-medium">Out of stock</th>
								<th className="py-2 text-right font-medium">In stock</th>
							</tr>
						</thead>
						<tbody>
							{shown.map((s) => (
								<tr
									key={s.merchant_id}
									onClick={() => onSelectStore?.(s.merchant_id)}
									className="cursor-pointer border-b border-border/60 hover:bg-surface-subtle"
								>
									<td className="py-2.5 pr-3 text-content">
										{s.store_name || `Store ${s.merchant_id}`}
										{s.store_name && (
											<span className="ml-2 text-xs text-content-subtle">#{s.merchant_id}</span>
										)}
										{s.merchant_type && s.merchant_type !== "express" && (
											<span title={`Store type: ${s.merchant_type}`} className="ml-2 rounded bg-surface-subtle px-1.5 py-0.5 text-[10px] text-content-subtle">
												slower delivery
											</span>
										)}
									</td>
									<td className="py-2.5 text-right tabular-nums text-content-muted">
										{formatNumber(s.skus_listed)}<span className="text-content-subtle"> / {formatNumber(range)}</span>
									</td>
									<td className="py-2.5 text-right tabular-nums text-content-muted">
										{formatNumber(s.skus_out_of_stock)}
									</td>
									<td className={`py-2.5 text-right tabular-nums ${stockClass(s.distribution_pct)}`}>
										{pct(s.distribution_pct)}
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
