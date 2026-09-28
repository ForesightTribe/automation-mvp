import { useState } from "react";
import { Search } from "lucide-react";
import { PageHeader } from "../../components/ui/PageHeader";
import { Card } from "../../components/ui/Card";
import { DataTable } from "../../components/ui/DataTable";
import { Pagination } from "../../components/ui/Pagination";
import { ViewToggle } from "../../components/ui/ViewToggle";
import { Select } from "../../components/ui/Select";
import { ExportButton } from "../../components/ui/ExportButton";
import { Loading } from "../../components/feedback/Loading";
import { ErrorState } from "../../components/feedback/ErrorState";
import {
	formatCompactCurrency,
	formatCurrency,
	formatDate,
	formatNumber,
	formatPercent,
} from "../../lib/format";
import { PriorityChip, StatusChip } from "./components/PriorityChip";
import { SkuTable } from "./components/SkuTable";
import { PoDrawer } from "./components/PoDrawer";
import { PoKpiTile } from "./components/PoKpiTile";
import { usePoSummary, usePoInsights, usePoSkus, usePoExport } from "./hooks";

/**
 * Purchase orders — what Blinkit ordered, how much of it arrived, and which POs still
 * have money sitting undelivered.
 *
 * "Undelivered value" is short units × landing rate. On an open PO that is value still
 * to come; on a closed one it is value missed. The two are counted separately
 * everywhere, and fill rate uses closed POs only — an open PO has delivered nothing yet
 * by definition.
 */
const VIEWS = [
	{ value: "po", label: "PO insights" },
	{ value: "sku", label: "SKU insights" },
];

// "open", "closed" and "cancelled" group the marketplace's own states; the rest
// are those states as Blinkit writes them. "Closed" means settled — delivered or
// expired, cancelled excluded.
const STATUSES = [
	["open", "Open"],
	["closed", "Closed"],
	["Unscheduled", "Unscheduled"],
	["Scheduled", "Scheduled"],
	["Fulfilled", "Fulfilled"],
	["Expired", "Expired"],
	["cancelled", "Cancelled"],
	["", "All statuses"],
];

export const PurchaseOrdersPage = () => {
	const [view, setView] = useState("po");
	const [search, setSearch] = useState("");
	const [status, setStatus] = useState("open");
	const [page, setPage] = useState(1);
	// The PO whose drawer is open.
	const [openPo, setOpenPo] = useState(null);
	// One switch for the whole strip: the tiles open and close together.
	const [comparing, setComparing] = useState(false);

	const summary = usePoSummary();
	const isSku = view === "sku";
	// Every PO in the window. The service orders them: still worth chasing first,
	// settled below. The view not on screen is disabled rather than unmounted.
	// Ordered by the API so a header sorts every PO, not the page in hand.
	const [poSort, setPoSort] = useState({ key: null, order: "desc" });
	const table = usePoInsights({
		scope: "all",
		search: isSku ? "" : search,
		status,
		page,
		sort: poSort.key,
		order: poSort.order,
	});
	// Ordered by the API so a header sorts every SKU, not the page in hand.
	const [skuSort, setSkuSort] = useState({ key: null, order: "desc" });
	const skus = usePoSkus({
		search: isSku ? search : "",
		page,
		sort: skuSort.key,
		order: skuSort.order,
	});
	// The file holds both views, so it does not change with the tab.
	const exporter = usePoExport("all", status);
	const s = summary.data;

	const tile = () => ({
		open: comparing,
		onToggle: () => setComparing((was) => !was),
	});

	const onView = (v) => {
		setView(v);
		setSearch("");
		setPage(1);
	};
	const onStatus = (v) => {
		setStatus(v);
		setPage(1);
	};
	const onSearch = (v) => {
		setSearch(v);
		setPage(1);
	};

	const columns = [
		{
			key: "po_number",
			label: "PO number",
			render: (r) => (
				<button
					type="button"
					onClick={() => setOpenPo(r.po_number)}
					className="font-medium text-content underline decoration-border underline-offset-4 tabular-nums transition-colors hover:decoration-content"
				>
					{r.po_number}
				</button>
			),
		},
		{
			key: "facility_name",
			label: "Warehouse & city",
			sortValue: (r) => `${r.city_name ?? ""} ${r.facility_name ?? ""}`,
			render: (r) => (
				<span className="block min-w-0">
					<span className="block truncate text-content">
						{r.facility_name ?? "—"}
					</span>
					<span className="text-xs text-content-subtle">
						{r.city_name ?? ""}
					</span>
				</span>
			),
		},
		{
			key: "priority",
			label: "Priority",
			sortValue: (r) => ({ high: 3, medium: 2, low: 1 })[r.priority] ?? 0,
			render: (r) => <PriorityChip priority={r.priority} />,
		},
		{
			key: "po_state",
			label: "Status",
			render: (r) => <StatusChip state={r.po_state} />,
		},
		{
			key: "short_lines",
			label: "Short SKUs",
			align: "right",
			sortValue: (r) => r.short_lines,
			render: (r) => (
				<span className="tabular-nums">
					{r.short_lines}
					<span className="text-content-subtle"> / {r.lines}</span>
				</span>
			),
		},
		{
			key: "undelivered_value",
			label: "Undelivered",
			align: "right",
			render: (r) => (
				<span
					className={`tabular-nums ${r.undelivered_value > 0 ? "font-medium text-danger" : "text-content-muted"}`}
				>
					{formatCurrency(r.undelivered_value)}
				</span>
			),
		},
		{
			key: "schedule_date",
			label: "Delivery slot",
			sortValue: (r) => r.schedule_date ?? "",
			render: (r) =>
				r.schedule_date ? (
					<button
						type="button"
						onClick={() => setOpenPo(r.po_number)}
						className="whitespace-nowrap tabular-nums text-content underline decoration-border underline-offset-4 transition-colors hover:decoration-content"
					>
						{new Date(r.schedule_date).toLocaleString("en-IN", {
							day: "numeric",
							month: "short",
							hour: "2-digit",
							minute: "2-digit",
						})}
					</button>
				) : r.needs_booking ? (
					<span className="rounded-full bg-danger-soft px-2 py-0.5 text-xs font-medium whitespace-nowrap text-danger">
						Not booked
					</span>
				) : (
					<span className="text-content-subtle">—</span>
				),
		},
		{
			key: "days_to_expiry",
			label: "Expires",
			align: "right",
			sortValue: (r) => r.days_to_expiry ?? 9999,
			render: (r) =>
				r.days_to_expiry === null ? (
					<span className="text-content-subtle">—</span>
				) : r.days_to_expiry < 0 ? (
					<span className="whitespace-nowrap text-content-subtle">
						{formatDate(r.expiry_date)}
					</span>
				) : (
					<span
						className={`tabular-nums whitespace-nowrap ${
							r.days_to_expiry <= 3 && r.is_open
								? "font-medium text-danger"
								: "text-content"
						}`}
					>
						in {r.days_to_expiry} days
					</span>
				),
		},
		{
			key: "issue_date",
			label: "Raised",
			align: "right",
			sortValue: (r) => r.issue_date ?? "",
			render: (r) => (
				<span className="whitespace-nowrap text-content-muted">
					{formatDate(r.issue_date)}
				</span>
			),
		},
	];

	return (
		<div className="flex flex-col gap-6">
			<PageHeader
				title="Purchase Orders"
				subtitle="What Blinkit ordered, what arrived, and what is still undelivered."
			/>

			{summary.isLoading && <Loading label="Loading purchase orders…" />}
			{summary.error && (
				<ErrorState
					message={summary.error.message}
					onRetry={summary.refetch}
				/>
			)}

			{s && (
				<div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
					<PoKpiTile
						label="PO value"
						value={{
							display: formatCompactCurrency(s.po_value),
							raw: s.po_value,
						}}
						hint={`${formatNumber(s.open_pos + s.closed_pos)} POs raised`}
						delta={s.po_value_delta}
						prev={s.prev_po_value}
						color="#0284c7"
						format={formatCompactCurrency}
						{...tile()}
					/>
					<PoKpiTile
						label="Fill rate"
						value={{
							display:
								s.fill_rate === null
									? "—"
									: formatPercent(s.fill_rate, 1),
							raw: s.fill_rate,
						}}
						hint={`${formatNumber(s.closed_pos)} closed POs · ${formatNumber(s.short_pos)} filled short`}
						delta={s.fill_rate_delta}
						prev={s.prev_fill_rate}
						color="#16a34a"
						format={(v) => formatPercent(v, 1)}
						{...tile()}
					/>
					<PoKpiTile
						label="Missed on closed POs"
						value={{
							display: formatCompactCurrency(s.value_missed),
							raw: s.value_missed,
						}}
						hint="Short units × landing rate"
						delta={s.value_missed_delta}
						goodWhenDown
						prev={s.prev_value_missed}
						color="#b3261e"
						format={formatCompactCurrency}
						{...tile()}
					/>
					<PoKpiTile
						label="Still to be delivered"
						value={{
							display: formatCompactCurrency(s.value_at_risk),
							raw: s.value_at_risk,
						}}
						hint={`${formatNumber(s.open_pos)} POs still open`}
						// A snapshot of what is open now, not a quantity for the
						// window: no comparison.
						note
						color="#a65f00"
						format={formatCompactCurrency}
						{...tile()}
					/>
				</div>
			)}

			<div className="flex flex-wrap items-center justify-between gap-3">
				<ViewToggle
					options={VIEWS}
					value={view}
					onChange={onView}
					size="lg"
				/>
				<div className="flex flex-col items-end gap-1">
					<ExportButton
						onExport={exporter.run}
						busy={exporter.busy}
						disabled={!s}
						label="Export to Excel"
					/>
					{exporter.error && (
						<span className="text-xs text-danger">
							{exporter.error}
						</span>
					)}
				</div>
			</div>

			<Card>
				<div className="mb-4 flex flex-wrap items-center justify-between gap-3">
					{/* SKU rows have no state of their own — they span every PO the SKU
					    appears on — so the filter belongs to the PO view only. */}
					{!isSku ? (
						<Select
							value={status}
							options={STATUSES}
							onChange={onStatus}
							ariaLabel="Filter by status"
							className="min-w-[8rem]"
						/>
					) : (
						<span />
					)}
					<label className="relative min-w-[14rem] flex-1 sm:max-w-xs">
						<Search
							size={14}
							aria-hidden
							className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-content-subtle"
						/>
						<input
							type="search"
							value={search}
							onChange={(e) => onSearch(e.target.value)}
							placeholder={
								isSku ? "Search SKU" : "Search PO number"
							}
							aria-label={
								isSku ? "Search SKU" : "Search PO number"
							}
							className="w-full rounded-lg border border-border bg-card py-2 pr-3 pl-8 text-sm text-content outline-none transition-colors placeholder:text-content-subtle focus:border-content-subtle focus:ring-4 focus:ring-brand/12"
						/>
					</label>
				</div>

				{isSku ? (
					<SkuTable
						query={skus}
						onPage={setPage}
						sort={skuSort}
						onSort={(key, order) => {
							setSkuSort({ key, order });
							setPage(1);
						}}
					/>
				) : (
					<>
						{table.isLoading && <Loading label="Loading POs…" />}
						{table.error && (
							<ErrorState
								message={table.error.message}
								onRetry={table.refetch}
							/>
						)}
						{table.data && table.data.items.length === 0 && (
							<p className="py-8 text-center text-sm text-content-muted">
								No purchase orders in this period.
							</p>
						)}
						{table.data && table.data.items.length > 0 && (
							<>
								<DataTable
									columns={columns}
									rows={table.data.items}
									rowKey={(r) => r.po_number}
									sortKey={poSort.key}
									sortOrder={poSort.order}
									onSortChange={(key, order) => {
										setPoSort({ key, order });
										setPage(1);
									}}
									minWidth={900}
									maxHeight={560}
								/>
								<Pagination
									page={table.data.page}
									pages={table.data.pages}
									total={table.data.total}
									limit={table.data.limit}
									onChange={setPage}
								/>
							</>
						)}
					</>
				)}
			</Card>
			<PoDrawer poNumber={openPo} onClose={() => setOpenPo(null)} />
		</div>
	);
};
