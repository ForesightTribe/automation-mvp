import { usePricing } from "../hooks";
import { Card } from "../../../components/ui/Card";
import { MetricTile } from "../../../components/ui/MetricTile";
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

	// Summary tiles, all three counted from the same response the table uses.
	const widest = rows.reduce((best, r) => {
		const spread = (r.max_price ?? 0) - (r.min_price ?? 0);
		return spread > (best?.spread ?? -1)
			? { spread, name: r.product_name || r.platform_product_id }
			: best;
	}, null);
	const discounts = rows
		.map((r) => r.avg_discount)
		.filter((v) => v !== null && v !== undefined);
	const avgDiscount = discounts.length
		? discounts.reduce((a, b) => a + b, 0) / discounts.length
		: null;

	const columns = [
		{
			key: "product_name",
			label: "Products",
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
			label: "Typical/Unit",
			align: "right",
			render: (r) => formatUnitPrice(r.unit_price_median, r.pack_uom),
		},
		{
			key: "avg_discount",
			label: "Avg. discount",
			align: "right",
			render: (r) => pct(r.avg_discount),
		},
	];

	return (
		<Card title="Price differences between stores">
			{/* The tiles are a summary, not a full-width strip: they fill about half
			    the card and the table runs full width beneath. */}
			{!isLoading && !error && rows.length > 0 && (
				<div className="mb-5 grid max-w-4xl grid-cols-1 gap-4 sm:grid-cols-3">
					<MetricTile
						label="Highest price difference"
						value={formatCurrency(widest?.spread)}
						hint={widest?.name}
					/>
					<MetricTile
						label="Average discount"
						value={pct(avgDiscount)}
						hint="across all products"
					/>
					<MetricTile
						label="Stores monitored"
						value={formatNumber(data?.stores_scraped)}
						hint="total unique stores"
					/>
				</div>
			)}
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
