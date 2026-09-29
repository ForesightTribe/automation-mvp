import { Drawer, DrawerStat } from "../../../components/ui/Drawer";
import { DataTable } from "../../../components/ui/DataTable";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import {
	formatCurrency,
	formatDate,
	formatNumber,
	formatPercent,
} from "../../../lib/format";
import { StatusChip } from "./PriorityChip";
import { useSkuPos } from "../hooks";

/**
 * One SKU across every PO that carried it.
 *
 * The table behind this ranks SKUs but cannot answer the question a rank
 * immediately raises — which POs, at which warehouses, and are they open or
 * settled. Rather than send the reader to another screen to find out, the row
 * opens onto its own POs.
 *
 * ⚠️ The stats cover the selected window; the PO list below covers all time.
 * The panel states which is which.
 */
const columns = [
	{
		key: "po_number",
		label: "PO",
		render: (r) => (
			<span className="tabular-nums text-content">{r.po_number}</span>
		),
	},
	{
		key: "po_state",
		label: "Status",
		render: (r) => <StatusChip state={r.po_state} />,
	},
	{
		key: "facility_name",
		label: "Warehouse",
		render: (r) => (
			<span className="text-content-muted" title={r.facility_name ?? ""}>
				{r.facility_name ?? "—"}
			</span>
		),
	},
	{
		key: "issue_date",
		label: "Issued",
		align: "right",
		render: (r) => (
			<span className="tabular-nums text-content-muted">
				{r.issue_date ? formatDate(r.issue_date) : "—"}
			</span>
		),
	},
	{
		key: "units_ordered",
		label: "Ordered",
		align: "right",
		render: (r) => (
			<span className="tabular-nums">
				{formatNumber(r.units_ordered ?? 0)}
			</span>
		),
	},
	{
		key: "received_qty",
		label: "Received",
		align: "right",
		render: (r) => (
			<span className="tabular-nums">
				{formatNumber(r.received_qty ?? 0)}
			</span>
		),
	},
	{
		key: "remaining_quantity",
		label: "Remaining",
		align: "right",
		render: (r) => (
			<span
				className={`tabular-nums ${
					r.remaining_quantity > 0
						? "text-content"
						: "text-content-muted"
				}`}
			>
				{formatNumber(r.remaining_quantity ?? 0)}
			</span>
		),
	},
	{
		key: "total_amount",
		label: "Value",
		align: "right",
		render: (r) => (
			<span className="tabular-nums text-content-muted">
				{r.total_amount == null ? "—" : formatCurrency(r.total_amount)}
			</span>
		),
	},
];

export const SkuDrawer = ({ sku, onClose }) => {
	const { data, isLoading, error, refetch } = useSkuPos(sku?.item_id);

	return (
		<Drawer
			open={Boolean(sku)}
			onClose={onClose}
			title={sku?.name ?? sku?.item_id ?? ""}
			subtitle={sku?.item_id}
		>
			{sku && (
				<div className="flex flex-col gap-6">
					<div className="grid grid-cols-2 gap-px bg-border">
						<DrawerStat
							label="POs open"
							value={`${formatNumber(sku.open_po_count)} / ${formatNumber(sku.po_count)}`}
							hint="still awaiting delivery"
						/>
						<DrawerStat
							label="Fill rate"
							value={
								sku.fill_rate === null
									? "—"
									: formatPercent(sku.fill_rate, 1)
							}
							hint="on settled POs"
						/>
						<DrawerStat
							label="Units short"
							value={formatNumber(sku.units_short)}
							hint="never arrived, settled POs"
						/>
						<DrawerStat
							label="Units awaiting"
							value={formatNumber(sku.units_not_due)}
							hint="still to come, open POs"
						/>
						<DrawerStat
							label="Missed"
							value={formatCurrency(sku.missed_value)}
							hint="no longer recoverable"
						/>
						<DrawerStat
							label="Value on open POs"
							value={formatCurrency(sku.open_value)}
							hint="ordered, not yet delivered"
						/>
					</div>

					<div className="flex flex-col gap-2">
						{/* Said outright: the figures above follow the picker, the
						    list below does not. */}
						<p className="text-xs text-content-muted">
							Every PO carrying this SKU, newest first. The
							figures above cover the selected window; this list
							covers all time.
						</p>

						{isLoading && <Loading label="Loading POs…" />}
						{error && (
							<ErrorState
								message={error.message}
								onRetry={refetch}
							/>
						)}
						{!isLoading && !error && !data?.items?.length && (
							<EmptyState message="No POs found for this SKU." />
						)}
						{data?.items?.length > 0 && (
							<DataTable
								columns={columns}
								rows={data.items}
								rowKey={(r) => r.po_number}
								minWidth={880}
								maxHeight={420}
							/>
						)}
					</div>
				</div>
			)}
		</Drawer>
	);
};
