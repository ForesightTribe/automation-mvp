import { useState } from "react";
import { useProductPos } from "../hooks";
import { Card } from "../../../components/ui/Card";
import { DataTable } from "../../../components/ui/DataTable";
import { Pagination } from "../../../components/ui/Pagination";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { formatCurrency, formatDate, formatNumber } from "../../../lib/format";

const num = (v) => (v === null || v === undefined ? "—" : formatNumber(v));

const COLUMNS = [
	{ key: "po_number", label: "PO #" },
	{
		key: "issue_date",
		label: "Date",
		render: (r) => formatDate(r.issue_date),
	},
	{ key: "po_state", label: "State", render: (r) => r.po_state || "—" },
	{
		key: "facility_name",
		label: "Facility",
		render: (r) => r.facility_name || "—",
	},
	{
		key: "units_ordered",
		label: "Ordered",
		align: "right",
		render: (r) => num(r.units_ordered),
	},
	{
		key: "received_qty",
		label: "Received",
		align: "right",
		render: (r) => num(r.received_qty),
	},
	{
		key: "total_amount",
		label: "Amount",
		align: "right",
		render: (r) =>
			r.total_amount === null || r.total_amount === undefined
				? "—"
				: formatCurrency(r.total_amount),
	},
];

/** This SKU's PO line history (tenant-wide, paginated). Own page state — it's not
 * tied to the page's date window. */
export const PoHistory = ({ itemId, marketplace }) => {
	const [page, setPage] = useState(1);
	// Zepto POs exist (brands.zepto.co.in has a whole PO Management section) but
	// nothing scrapes them yet, so `blinkit_po_items` holds none and the query
	// would always come back empty. Skip it rather than spend a request, and say
	// "not collected" — "no purchase orders" would be a claim about the client's
	// business rather than about our coverage.
	const isZepto = marketplace === "zepto";
	const { data, isLoading, error, refetch } = useProductPos(
		isZepto ? null : itemId,
		page,
	);
	const rows = data?.items ?? [];

	if (isZepto) {
		return (
			<Card title="Purchase order history">
				<EmptyState message="Purchase orders aren't collected for Zepto yet." />
			</Card>
		);
	}

	return (
		<Card title="Purchase order history">
			{isLoading && <Loading label="Loading POs…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading &&
				!error &&
				(rows.length === 0 ? (
					<EmptyState message="No purchase orders for this SKU." />
				) : (
					<>
						<DataTable
							columns={COLUMNS}
							rows={rows}
							rowKey={(r, i) => `${r.po_number}-${i}`}
						/>
						<Pagination
							page={data.page}
							pages={data.pages}
							total={data.total}
							limit={data.limit}
							onChange={setPage}
						/>
					</>
				))}
		</Card>
	);
};
