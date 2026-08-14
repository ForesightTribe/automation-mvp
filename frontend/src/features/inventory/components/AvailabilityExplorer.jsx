import { useMemo, useState } from "react";
import { useCities, useDistribution, useStores } from "../hooks";
import { Card } from "../../../components/ui/Card";
import { ViewToggle } from "../../../components/ui/ViewToggle";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { formatNumber } from "../../../lib/format";

const LENSES = [
	{ value: "city", label: "By city" },
	{ value: "store", label: "By store" },
	{ value: "product", label: "By product" },
];

const pct = (v) => (v === null || v === undefined ? "—" : `${Number(v).toFixed(1)}%`);

/** Colour In-stock% only. On-shelf varies with range strategy, so colouring it would
 *  cry wolf; in-stock below 90/97 is a genuine supply warning. */
const stockClass = (v) =>
	v === null || v === undefined
		? "text-content-subtle"
		: v < 90
			? "text-danger"
			: v < 97
				? "text-warning"
				: "text-content";

/**
 * The primary availability table — one table, three lenses, sortable, with a single
 * consistent interaction: **clicking a row opens the matching detail drawer.**
 *
 *   By city    → city drawer (its stores)      → a store there → store drawer
 *   By store   → store drawer (its products)
 *   By product → product drawer (its stores)
 *
 * The earlier version mixed patterns (city expanded inline, store opened an overlay,
 * product did nothing), which read as broken. Now every lens behaves identically:
 * the table ranks and sorts, and a click opens a drawer. Column headers sort. See
 * docs/darkstores.md.
 */
export const AvailabilityExplorer = ({ kind = "main", onSelectStore, onSelectProduct, onSelectCity }) => {
	const [lens, setLens] = useState("city");
	const [sort, setSort] = useState({ key: null, dir: "desc" });

	const cities = useCities(kind);
	const storesAll = useStores({ kind });
	const products = useDistribution(kind);

	const range = storesAll.data?.active_range ?? 0;
	const scraped = storesAll.data?.stores_scraped ?? 0;

	const view = lens;
	const source = lens === "city" ? cities : lens === "store" ? storesAll : products;

	const setLensReset = (v) => {
		setLens(v);
		setSort({ key: null, dir: "desc" });
	};

	// Column defs per view: label, alignment, cell renderer, and a numeric sort value.
	const columns = useMemo(() => {
		if (view === "store") {
			return [
				{ key: "name", label: "Store", render: (r) => (
					<span>
						{r.store_name || `Store ${r.merchant_id}`}
						{r.store_name && (
							<span className="ml-2 text-xs text-content-subtle">#{r.merchant_id}</span>
						)}
						<span className="ml-2 text-xs capitalize text-content-subtle">{r.city}</span>
						{r.merchant_type && r.merchant_type !== "express" && (
							<span title={`Store type: ${r.merchant_type}`} className="ml-2 rounded bg-surface-subtle px-1.5 py-0.5 text-[10px] text-content-subtle">
								slower delivery
							</span>
						)}
					</span>
				), sort: (r) => r.store_name || r.merchant_id },
				{ key: "skus_listed", label: "On shelf", align: "right", render: (r) => (
					<span>{formatNumber(r.skus_listed)}<span className="text-content-subtle"> / {formatNumber(range)}</span></span>
				), sort: (r) => r.skus_listed },
				{ key: "skus_out_of_stock", label: "Out of stock", align: "right", render: (r) => formatNumber(r.skus_out_of_stock), sort: (r) => r.skus_out_of_stock },
				{ key: "skus_not_listed", label: "Not carried", align: "right", render: (r) => formatNumber(r.skus_not_listed), sort: (r) => r.skus_not_listed },
				{ key: "distribution_pct", label: "In stock", align: "right", render: (r) => <span className={stockClass(r.distribution_pct)}>{pct(r.distribution_pct)}</span>, sort: (r) => r.distribution_pct },
			];
		}
		if (view === "product") {
			return [
				{ key: "name", label: "Product", render: (r) => r.product_name || r.platform_product_id, sort: (r) => r.product_name || "" },
				{ key: "stores_listed", label: "Stores carrying it", align: "right", render: (r) => (
					<span>{formatNumber(r.stores_listed)}<span className="text-content-subtle"> / {formatNumber(scraped)}</span></span>
				), sort: (r) => r.stores_listed },
				{ key: "reach_pct", label: "Store coverage", align: "right", render: (r) => pct(r.reach_pct), sort: (r) => r.reach_pct },
				{ key: "stores_out_of_stock", label: "Out of stock", align: "right", render: (r) => formatNumber(r.stores_out_of_stock), sort: (r) => r.stores_out_of_stock },
				{ key: "distribution_pct", label: "In stock", align: "right", render: (r) => <span className={stockClass(r.distribution_pct)}>{pct(r.distribution_pct)}</span>, sort: (r) => r.distribution_pct },
			];
		}
		return [
			{ key: "city", label: "City", render: (r) => <span className="capitalize">{r.city || "—"}</span>, sort: (r) => r.city || "" },
			{ key: "stores", label: "Stores", align: "right", render: (r) => formatNumber(r.stores), sort: (r) => r.stores },
			{ key: "skus_out_of_stock", label: "Out of stock", align: "right", render: (r) => formatNumber(r.skus_out_of_stock), sort: (r) => r.skus_out_of_stock },
			{ key: "skus_not_listed", label: "Missing listings", align: "right", render: (r) => formatNumber(r.skus_not_listed), sort: (r) => r.skus_not_listed },
			{ key: "distribution_pct", label: "In stock", align: "right", render: (r) => <span className={stockClass(r.distribution_pct)}>{pct(r.distribution_pct)}</span>, sort: (r) => r.distribution_pct },
		];
	}, [view, range, scraped]);

	const rawRows =
		view === "store"
			? source.data?.stores ?? []
			: view === "product"
				? source.data?.skus ?? []
				: source.data?.cities ?? [];

	const rows = useMemo(() => {
		if (!sort.key) return rawRows;
		const col = columns.find((c) => c.key === sort.key);
		if (!col) return rawRows;
		const dir = sort.dir === "asc" ? 1 : -1;
		return [...rawRows].sort((a, b) => {
			const av = col.sort(a), bv = col.sort(b);
			if (typeof av === "string") return av.localeCompare(bv) * dir;
			return ((av ?? 0) - (bv ?? 0)) * dir;
		});
	}, [rawRows, sort, columns]);

	const onHeader = (key) =>
		setSort((s) => (s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "desc" }));

	const onRow = (r) => {
		if (view === "product") onSelectProduct?.(r.platform_product_id);
		else if (view === "store") onSelectStore?.(r.merchant_id);
		else onSelectCity?.(r.city); // city lens → city drawer
	};

	const subtitle =
		lens === "product"
			? `Each of your ${formatNumber(range)} products, across ${formatNumber(scraped)} stores`
			: lens === "store"
				? `${formatNumber(scraped)} stores · click any row for its full shelf`
				: `${formatNumber((cities.data?.cities ?? []).length)} cities · click any row for its stores`;

	return (
		<Card>
			<div className="mb-4 flex flex-wrap items-start justify-between gap-3">
				<div>
					<h2 className="font-display text-base font-semibold text-content">
						Where you are on the shelf
					</h2>
					<p className="text-xs text-content-subtle">{subtitle}</p>
				</div>
				<ViewToggle options={LENSES} value={lens} onChange={setLensReset} />
			</div>

			{source.isLoading ? (
				<Loading label="Loading…" />
			) : source.error ? (
				<ErrorState message={source.error.message} onRetry={source.refetch} />
			) : rows.length === 0 ? (
				<p className="py-8 text-center text-sm text-content-subtle">Nothing in this window.</p>
			) : (
				<div className="overflow-auto" style={{ maxHeight: 520 }}>
					<table className="w-full border-collapse text-sm">
						<thead className="sticky top-0 z-10 bg-card">
							<tr className="border-b border-border text-content-subtle">
								{columns.map((c) => (
									<th
										key={c.key}
										onClick={() => onHeader(c.key)}
										className={`cursor-pointer select-none px-3 py-2 font-medium hover:text-content ${
											c.align === "right" ? "text-right" : "text-left"
										}`}
									>
										{c.label}
										{sort.key === c.key && (
											<span className="ml-1 text-[10px]">{sort.dir === "asc" ? "▲" : "▼"}</span>
										)}
									</th>
								))}
							</tr>
						</thead>
						<tbody>
							{rows.map((r, i) => (
								<tr
									key={r.merchant_id || r.platform_product_id || r.city || i}
									onClick={() => onRow(r)}
									className="cursor-pointer border-b border-border/60 hover:bg-surface-subtle"
								>
									{columns.map((c) => (
										<td
											key={c.key}
											className={`px-3 py-2.5 ${c.align === "right" ? "text-right tabular-nums" : "text-content"}`}
										>
											{c.render(r)}
										</td>
									))}
								</tr>
							))}
						</tbody>
					</table>
				</div>
			)}
		</Card>
	);
};
