import { useState } from "react";
import { DataTable } from "../../../components/ui/DataTable";
import { SkuDrawer } from "./SkuDrawer";
import { Pagination } from "../../../components/ui/Pagination";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import {
	formatCurrency,
	formatDate,
	formatNumber,
	formatPercent,
} from "../../../lib/format";

/**
 * The shortfall per SKU across every PO in the window: which products Blinkit keeps
 * ordering and not receiving, and how much of that is still to come versus already lost.
 */
const columns = [
	{
		key: "name",
		label: "SKU",
		sortValue: (r) => r.name ?? r.item_id,
		render: (r) => (
			<span className="block min-w-0">
				<span
					className="block truncate text-content"
					title={r.name ?? ""}
				>
					{r.name ?? r.item_id}
				</span>
				<span className="text-xs text-content-subtle tabular-nums">
					{r.item_id}
				</span>
			</span>
		),
	},
	{
		key: "drr",
		label: "DRR",
		align: "right",
		hint: "Daily run rate — units sold per day over the selected window, from the sales feed.",
		render: (r) => (
			<span className="tabular-nums">
				{r.drr == null ? "—" : formatNumber(Math.round(r.drr))}
			</span>
		),
	},
	{
		key: "doi_days",
		label: "DOI (FE+BE)",
		align: "right",
		hint: "Days of inventory: stock on hand now — front end plus back end — divided by the daily run rate. Reads the latest stock snapshot, so it does not move with the date picker.",
		render: (r) => (
			<span className="tabular-nums">
				{r.doi_days == null ? "—" : `${Math.round(r.doi_days)} days`}
			</span>
		),
	},
	{
		key: "po_units",
		label: "PO Units",
		align: "right",
		hint: "Units ordered on POs that have settled — the same set Fill Rate is measured over, so the three columns reconcile. Open POs are counted under Not yet due.",
		sortValue: (r) => r.units_received + r.units_short,
		render: (r) => (
			<span className="tabular-nums">
				{formatNumber(r.units_received + r.units_short)}
			</span>
		),
	},
	{
		key: "units_received",
		label: "GRN Units",
		align: "right",
		hint: "Units actually received against settled POs.",
		render: (r) => (
			<span className="tabular-nums">
				{formatNumber(r.units_received)}
			</span>
		),
	},
	{
		key: "fill_rate",
		label: "Fill Rate (%)",
		align: "right",
		hint: "Received divided by ordered, on settled POs only. Cancelled POs are excluded: the order was withdrawn, so nothing was ever asked for.",
		render: (r) => (
			<span className="tabular-nums">
				{r.fill_rate === null ? "—" : formatPercent(r.fill_rate, 2)}
			</span>
		),
	},
	{
		key: "deficit",
		label: "Deficit (%)",
		align: "right",
		hint: "The share of ordered units that never arrived — the remainder of Fill Rate.",
		sortValue: (r) => (r.fill_rate === null ? -1 : 1 - r.fill_rate),
		render: (r) => (
			<span
				className={`tabular-nums ${
					r.fill_rate !== null && 1 - r.fill_rate > 0
						? "text-content"
						: "text-content-muted"
				}`}
			>
				{r.fill_rate === null ? "—" : formatPercent(1 - r.fill_rate, 2)}
			</span>
		),
	},
	{
		key: "missed_value",
		label: "Missed",
		align: "right",
		hint: "Cost value of units on settled POs that never arrived. No longer recoverable, unlike value on open POs.",
		render: (r) => (
			<span
				className={`tabular-nums ${r.missed_value > 0 ? "font-medium text-danger" : "text-content-muted"}`}
			>
				{formatCurrency(r.missed_value)}
			</span>
		),
	},
	{
		key: "open_po_count",
		label: "POs open",
		align: "right",
		hint: "POs still awaiting delivery, against every PO this SKU has appeared on in the window.",
		render: (r) => (
			<span className="tabular-nums text-content-muted">
				{formatNumber(r.open_po_count)}
				<span className="text-content-subtle">
					{" "}
					/ {formatNumber(r.po_count)}
				</span>
			</span>
		),
	},
	{
		key: "cities",
		label: "Cities",
		align: "right",
		hint: "Distinct cities whose warehouses ordered this SKU in the window.",
		render: (r) => (
			<span className="tabular-nums text-content-muted">
				{formatNumber(r.cities)}
			</span>
		),
	},
	{
		key: "last_ordered",
		label: "Last ordered",
		align: "right",
		hint: "Issue date of the most recent PO carrying this SKU.",
		render: (r) => (
			<span className="tabular-nums text-content-muted">
				{r.last_ordered ? formatDate(r.last_ordered) : "—"}
			</span>
		),
	},
];

export const SkuTable = ({ query, onPage, sort, onSort }) => {
	const [openSku, setOpenSku] = useState(null);

	if (query.isLoading) return <Loading label="Loading SKUs…" />;
	if (query.error)
		return (
			<ErrorState message={query.error.message} onRetry={query.refetch} />
		);
	if (!query.data) return null;
	if (query.data.items.length === 0)
		return (
			<p className="py-8 text-center text-sm text-content-muted">
				No SKUs ordered in this period.
			</p>
		);

	return (
		<>
			<DataTable
				columns={columns}
				rows={query.data.items}
				rowKey={(r) => r.item_id}
				onRowClick={setOpenSku}
				sortKey={sort?.key}
				sortOrder={sort?.order}
				onSortChange={onSort}
				minWidth={1320}
				maxHeight={560}
			/>
			<Pagination
				page={query.data.page}
				pages={query.data.pages}
				total={query.data.total}
				limit={query.data.limit}
				onChange={onPage}
			/>
			<SkuDrawer sku={openSku} onClose={() => setOpenSku(null)} />
		</>
	);
};
