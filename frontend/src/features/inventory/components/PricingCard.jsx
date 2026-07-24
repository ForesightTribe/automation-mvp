import { usePricing } from "../hooks";
import { Card } from "../../../components/ui/Card";
import { DataTable } from "../../../components/ui/DataTable";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import {
	formatCurrency,
	formatNumber,
	formatUnitPrice,
} from "../../../lib/format";

const pct = (v) =>
	v === null || v === undefined ? "—" : `${Number(v).toFixed(1)}%`;

/**
 * Per-SKU price dispersion across stores (min / median / max) + avg discount, from
 * the latest snapshot per store. The per-unit "Typical" (₹/100 ml · 100 g · piece)
 * makes SKUs of different pack sizes comparable. Surfaces where the same SKU is
 * priced differently store-to-store. A table (the numbers are the point).
 */
export const PricingCard = ({ kind = "main" }) => {
	const { data, isLoading, error, refetch } = usePricing(kind);
	const rows = data?.skus ?? [];

	const columns = [
		{
			key: "product_name",
			label: "Product",
			render: (r) => r.product_name || r.platform_product_id,
		},
		{
			key: "stores",
			label: "Stores",
			align: "right",
			render: (r) => formatNumber(r.stores),
		},
		{
			key: "min_price",
			label: "Cheapest",
			align: "right",
			render: (r) => formatCurrency(r.min_price),
		},
		{
			key: "median_price",
			label: "Typical",
			align: "right",
			render: (r) => formatCurrency(r.median_price),
		},
		{
			key: "max_price",
			label: "Dearest",
			align: "right",
			render: (r) => formatCurrency(r.max_price),
		},
		{
			key: "unit_price_median",
			label: "Typical / unit",
			align: "right",
			render: (r) => formatUnitPrice(r.unit_price_median, r.pack_uom),
		},
		{
			key: "avg_discount",
			label: "Avg discount",
			align: "right",
			render: (r) => pct(r.avg_discount),
		},
	];

	return (
		<Card title="Price differences between stores">
			{isLoading && <Loading label="Loading prices…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading &&
				!error &&
				(rows.length === 0 ? (
					<EmptyState message="No prices captured in this window." />
				) : (
					<DataTable
						columns={columns}
						rows={rows}
						rowKey={(r) => r.platform_product_id}
						maxHeight={420}
					/>
				))}
		</Card>
	);
};
