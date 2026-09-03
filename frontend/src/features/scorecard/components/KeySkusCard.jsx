import { useEffect, useState } from "react";
import { useKeySkus } from "../hooks";
import { Card } from "../../../components/ui/Card";
import { DataTable } from "../../../components/ui/DataTable";
import { Pagination } from "../../../components/ui/Pagination";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { formatCompactCurrency, formatNumber } from "../../../lib/format";

const LIMIT = 20;

/** Key SKUs ranked by potential fill loss for the selected week — "which of my
 * products am I losing the most sales on". Server-paginated; resets to page 1
 * when the week changes. */
export const KeySkusCard = ({ from }) => {
	const [page, setPage] = useState(1);
	useEffect(() => {
		setPage(1);
	}, [from]);

	const { data, isLoading, error, refetch, isFetching } = useKeySkus({
		from,
		page,
		limit: LIMIT,
	});
	const rows = data?.items ?? [];
	// Which of the two the marketplace actually sent. Checked across the rows
	// rather than on the first one, so a single SKU with no shortfall does not
	// flip the whole column.
	const unitsColumn = rows.some((r) => r.units_short != null);

	const columns = [
		{
			key: "item_name",
			label: "SKU",
			render: (r) => (
				<div>
					<div className="font-medium text-content">
						{r.item_name || `#${r.item_id}`}
					</div>
					{r.variant_description && (
						<div className="text-xs text-content-muted">
							{r.variant_description}
						</div>
					)}
				</div>
			),
		},
		{
			key: "proxy_category",
			label: "Category",
			render: (r) => r.proxy_category || "—",
		},
		// Blinkit reports GMV per key SKU; Zepto sends units short instead and
		// leaves GMV null. One column, labelled for whichever arrived — the
		// alternative was rendering a unit count as currency.
		unitsColumn
			? {
					key: "units_short",
					label: "Units short",
					align: "right",
					render: (r) => formatNumber(r.units_short),
				}
			: {
					key: "total_gmv",
					label: "GMV",
					align: "right",
					render: (r) => formatCompactCurrency(r.total_gmv),
				},
		{
			key: "potential_loss",
			label: "Potential loss",
			align: "right",
			render: (r) => formatCompactCurrency(r.potential_loss),
		},
	];

	return (
		<Card title="Key SKUs at risk">
			{isLoading && <Loading label="Loading SKUs…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading &&
				!error &&
				(rows.length === 0 ? (
					<EmptyState message="No key SKUs for this week." />
				) : (
					<div className={isFetching ? "opacity-60 transition-opacity" : ""}>
						<DataTable
							columns={columns}
							rows={rows}
							rowKey={(r) => r.item_id}
						/>
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
