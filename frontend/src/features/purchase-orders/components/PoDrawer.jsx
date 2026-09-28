import { Drawer } from "../../../components/ui/Drawer";
import { DataTable } from "../../../components/ui/DataTable";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import {
	formatCurrency,
	formatDate,
	formatNumber,
	formatPercent,
} from "../../../lib/format";
import { StatusChip } from "./PriorityChip";
import { usePo } from "../hooks";

/**
 * One purchase order in full: its schedule, the people and place behind it, and every
 * line with what is still owed.
 */
const slot = (value) =>
	value
		? new Date(value).toLocaleString("en-IN", {
				weekday: "short",
				day: "numeric",
				month: "short",
				hour: "2-digit",
				minute: "2-digit",
			})
		: null;

const Stat = ({ label, value }) => (
	<div className="bg-card px-4 py-3">
		<div className="text-[11px] font-medium tracking-wide text-content-subtle uppercase">
			{label}
		</div>
		<div className="mt-0.5 text-sm font-semibold text-content tabular-nums">
			{value ?? "—"}
		</div>
	</div>
);

const Row = ({ label, children }) => (
	<div className="flex items-baseline justify-between gap-4 py-2">
		<span className="shrink-0 text-xs text-content-muted">{label}</span>
		<span className="min-w-0 text-right text-sm text-content">
			{children ?? "—"}
		</span>
	</div>
);

const itemColumns = (isOpen) => [
	{
		key: "name",
		label: "SKU",
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
		label: "Ordered",
		align: "right",
		hint: "Units Blinkit ordered on this line.",
		render: (r) => (
			<span className="tabular-nums">
				{formatNumber(r.units_ordered)}
			</span>
		),
	},
	{
		// Received is shown beside Ordered so the gap below reads as arithmetic
		// rather than a bare difference.
		key: "received",
		label: "Received",
		align: "right",
		hint: "Units actually delivered against this line.",
		sortValue: (r) => (r.units_ordered ?? 0) - (r.remaining_quantity ?? 0),
		render: (r) => (
			<span className="tabular-nums">
				{formatNumber(
					(r.units_ordered ?? 0) - (r.remaining_quantity ?? 0),
				)}
			</span>
		),
	},
	{
		key: "remaining_quantity",
		// The same number means two different things: on an open PO it is stock
		// still to come, on a settled one it is a shortfall that will not arrive.
		label: isOpen ? "Awaiting" : "Short",
		align: "right",
		hint: isOpen
			? "Units not yet delivered. This PO is still open, so these are still to come — not a shortfall."
			: "Units that never arrived. This PO has settled, so the gap is final.",
		render: (r) => (
			<span
				className={`tabular-nums ${
					r.remaining_quantity > 0
						? isOpen
							? "font-medium text-content"
							: "font-medium text-danger"
						: "text-content-muted"
				}`}
			>
				{formatNumber(r.remaining_quantity)}
			</span>
		),
	},
	{
		key: "line_fill",
		label: "Fill",
		align: "right",
		hint: "Received divided by ordered, for this line.",
		sortValue: (r) =>
			r.units_ordered
				? 1 - (r.remaining_quantity ?? 0) / r.units_ordered
				: -1,
		render: (r) =>
			r.units_ordered ? (
				<span className="tabular-nums text-content-muted">
					{formatPercent(
						1 - (r.remaining_quantity ?? 0) / r.units_ordered,
						0,
					)}
				</span>
			) : (
				<span className="text-content-subtle">—</span>
			),
	},
	{
		key: "landing_rate",
		label: "Landing rate",
		align: "right",
		render: (r) => (
			<span className="tabular-nums text-content-muted">
				{formatCurrency(r.landing_rate)}
			</span>
		),
	},
	{
		key: "owed_value",
		label: isOpen ? "Value to come" : "Value missed",
		hint: isOpen
			? "Cost of the units not yet delivered on this line. The PO is open, so this is still to come."
			: "Cost of the units that never arrived on this line. The PO has settled, so this is final.",
		align: "right",
		sortValue: (r) => (r.remaining_quantity ?? 0) * (r.landing_rate ?? 0),
		render: (r) => (
			<span className="tabular-nums">
				{formatCurrency(
					(r.remaining_quantity ?? 0) * (r.landing_rate ?? 0),
				)}
			</span>
		),
	},
	{
		key: "margin_percentage",
		label: "Margin",
		align: "right",
		render: (r) => (
			<span className="tabular-nums text-content-muted">
				{r.margin_percentage === null ||
				r.margin_percentage === undefined
					? "—"
					: `${r.margin_percentage.toFixed(1)}%`}
			</span>
		),
	},
];

export const PoDrawer = ({ poNumber, onClose }) => {
	const { data: po, isLoading, error, refetch } = usePo(poNumber);

	const ordered = po?.total_units_ordered ?? 0;
	const received = po?.total_grn_quantity ?? 0;
	const owed = (po?.items ?? []).reduce(
		(sum, i) => sum + (i.remaining_quantity ?? 0) * (i.landing_rate ?? 0),
		0,
	);

	return (
		<Drawer
			open={Boolean(poNumber)}
			onClose={onClose}
			title={poNumber ? `PO ${poNumber}` : ""}
			subtitle={
				po
					? [po.facility_name, po.city_name]
							.filter(Boolean)
							.join(" · ")
					: ""
			}
			stats={
				po && (
					<>
						<Stat
							label="PO value"
							value={formatCurrency(po.total_po_amount)}
						/>
						<Stat
							label="Received"
							value={
								ordered
									? `${formatPercent(received / ordered, 0)} of ${formatNumber(ordered)}`
									: "—"
							}
						/>
						<Stat
							label={
								po.is_open ? "Value on open PO" : "Value missed"
							}
							value={formatCurrency(owed)}
						/>
					</>
				)
			}
		>
			{isLoading && <Loading label="Loading PO…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}

			{po && (
				<div className="flex flex-col gap-6">
					<section>
						<h3 className="mb-1 text-xs font-semibold tracking-wide text-content-muted uppercase">
							Schedule
						</h3>
						<div className="divide-y divide-border">
							<Row label="Status">
								<StatusChip state={po.po_state} />
							</Row>
							<Row label="Delivery slot">
								{slot(po.schedule_date) ?? (
									<span className="text-danger">
										Not booked
									</span>
								)}
							</Row>
							<Row label="Slot booked on">
								{slot(po.scheduled_on)}
							</Row>
							<Row label="Raised">
								{formatDate(po.issue_date)}
							</Row>
							<Row label="Due">
								{formatDate(po.delivery_date)}
							</Row>
							<Row label="Expires">
								{formatDate(po.expiry_date)}
							</Row>
							<Row label="Delivery type">{po.delivery_type}</Row>
						</div>
					</section>

					<section>
						<h3 className="mb-1 text-xs font-semibold tracking-wide text-content-muted uppercase">
							Where and who
						</h3>
						<div className="divide-y divide-border">
							<Row label="Warehouse">{po.facility_name}</Row>
							<Row label="City">{po.city_name}</Row>
							<Row label="Address">{po.address}</Row>
							<Row label="Vendor">{po.vendor_name}</Row>
							<Row label="Platform contact">
								{po.pm_name
									? [po.pm_name, po.pm_phone]
											.filter(Boolean)
											.join(" · ")
									: null}
							</Row>
						</div>
					</section>

					<section>
						<h3 className="mb-2 text-xs font-semibold tracking-wide text-content-muted uppercase">
							Lines ({po.items?.length ?? 0})
						</h3>
						{po.items?.length ? (
							<DataTable
								columns={itemColumns(po.is_open ?? false)}
								rows={po.items}
								rowKey={(r) => r.line_id ?? r.item_id}
								minWidth={760}
								maxHeight={420}
								defaultSort="owed_value"
							/>
						) : (
							<p className="text-sm text-content-muted">
								No line items stored for this PO.
							</p>
						)}
					</section>
				</div>
			)}
		</Drawer>
	);
};
