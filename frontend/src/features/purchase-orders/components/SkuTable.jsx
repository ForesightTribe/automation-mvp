import { DataTable } from "../../../components/ui/DataTable";
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
		key: "units_ordered",
		label: "Units ordered",
		align: "right",
		render: (r) => (
			<span className="tabular-nums">
				{formatNumber(r.units_ordered)}
			</span>
		),
	},
	{
		key: "units_short",
		label: "Units short",
		align: "right",
		render: (r) => (
			<span
				className={`tabular-nums ${r.units_short > 0 ? "text-content" : "text-content-muted"}`}
			>
				{formatNumber(r.units_short)}
			</span>
		),
	},
	{
		key: "fill_rate",
		label: "Fill rate",
		align: "right",
		render: (r) => (
			<span className="tabular-nums">
				{r.fill_rate === null ? "—" : formatPercent(r.fill_rate, 1)}
			</span>
		),
	},
	{
		key: "open_value",
		label: "Still to come",
		align: "right",
		render: (r) => (
			<span className="tabular-nums text-content-muted">
				{formatCurrency(r.open_value)}
			</span>
		),
	},
	{
		key: "missed_value",
		label: "Missed",
		align: "right",
		render: (r) => (
			<span
				className={`tabular-nums ${r.missed_value > 0 ? "font-medium text-danger" : "text-content-muted"}`}
			>
				{formatCurrency(r.missed_value)}
			</span>
		),
	},
	{
		key: "short_po_count",
		label: "POs short",
		align: "right",
		render: (r) => (
			<span className="tabular-nums">
				{r.short_po_count}
				<span className="text-content-subtle"> / {r.po_count}</span>
			</span>
		),
	},
	{
		key: "cities",
		label: "Cities",
		align: "right",
		render: (r) => <span className="tabular-nums">{r.cities}</span>,
	},
	{
		key: "last_ordered",
		label: "Last ordered",
		align: "right",
		sortValue: (r) => r.last_ordered ?? "",
		render: (r) => (
			<span className="whitespace-nowrap text-content-muted">
				{formatDate(r.last_ordered)}
			</span>
		),
	},
];

export const SkuTable = ({ query, onPage }) => {
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
				minWidth={980}
				maxHeight={560}
			/>
			<Pagination
				page={query.data.page}
				pages={query.data.pages}
				total={query.data.total}
				limit={query.data.limit}
				onChange={onPage}
			/>
		</>
	);
};
