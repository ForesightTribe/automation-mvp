import { useEffect, useState } from "react";
import { useAvailability } from "../hooks";
import { Card } from "../../../components/ui/Card";
import { DataTable } from "../../../components/ui/DataTable";
import { Pagination } from "../../../components/ui/Pagination";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { useDateRange } from "../../../context/DateRangeContext";
import { formatCurrency, formatDate, formatNumber } from "../../../lib/format";

const LIMIT = 20;

const StockBadge = ({ inStock }) => (
	<span
		className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${
			inStock ? "bg-success/10 text-success" : "bg-danger/10 text-danger"
		}`}
	>
		<span className={`h-1.5 w-1.5 rounded-full ${inStock ? "bg-success" : "bg-danger"}`} />
		{inStock ? "In stock" : "Out"}
	</span>
);

/**
 * Store-level availability for own SKUs — latest snapshot per (marketplace, city,
 * product), out-of-stock first (server-sorted). Paginated: this is the raw
 * "where exactly am I out" detail behind the distribution summary.
 */
export const AvailabilityListCard = ({ kind = "main" }) => {
	const [page, setPage] = useState(1);
	const { days } = useDateRange();
	useEffect(() => {
		setPage(1);
	}, [days, kind]);

	const { data, isLoading, error, refetch, isFetching } = useAvailability({
		page,
		limit: LIMIT,
		kind,
	});
	const rows = data?.items ?? [];

	const columns = [
		{ key: "product_name", label: "Product", render: (r) => r.product_name || r.platform_product_id },
		{ key: "city", label: "City" },
		{ key: "marketplace", label: "MP", render: (r) => r.marketplace },
		{ key: "in_stock", label: "Status", render: (r) => <StockBadge inStock={r.in_stock} /> },
		{ key: "inventory", label: "Qty", align: "right", render: (r) => formatNumber(r.inventory) },
		{ key: "price", label: "Price", align: "right", render: (r) => formatCurrency(r.price) },
		{ key: "scraped_at", label: "Scraped", render: (r) => formatDate(r.scraped_at) },
	];

	return (
		<Card title="Location-level availability (out-of-stock first)">
			{isLoading && <Loading label="Loading availability…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading &&
				!error &&
				(rows.length === 0 ? (
					<EmptyState message="No own-SKU availability in this window." />
				) : (
					<div className={isFetching ? "opacity-60 transition-opacity" : ""}>
						<DataTable columns={columns} rows={rows} rowKey={(r, i) => `${r.platform_product_id}-${r.city}-${i}`} />
						<Pagination
							page={data.page}
							pages={data.pages}
							total={data.total}
							limit={data.limit}
							onChange={setPage}
						/>
					</div>
				))}
		</Card>
	);
};
