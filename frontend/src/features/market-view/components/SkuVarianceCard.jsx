import { useSkuVariance } from "../hooks";
import { useMarketView } from "../viewContext";
import { Card } from "../../../components/ui/Card";
import { DataTable } from "../../../components/ui/DataTable";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { formatCurrency, formatNumber } from "../../../lib/format";

/**
 * How far one SKU's price and availability drift between stores.
 *
 * One SKU is not one price. The spread between cheapest and dearest store is
 * the number to act on — a wide band is usually a stale override somewhere
 * rather than deliberate local pricing. Sorted widest spread first.
 */
export const SkuVarianceCard = () => {
	const { data, isLoading, error, refetch } = useSkuVariance();
	const { keyword } = useMarketView();
	const rows = data?.rows ?? [];

	const columns = [
		{ key: "sku", label: "SKU" },
		{ key: "pack", label: "Pack", render: (r) => r.pack || "—" },
		{ key: "stores", label: "Stores", align: "right", render: (r) => formatNumber(r.stores) },
		{ key: "min_price", label: "Min", align: "right", render: (r) => formatCurrency(r.min_price) },
		{ key: "max_price", label: "Max", align: "right", render: (r) => formatCurrency(r.max_price) },
		{ key: "avg_price", label: "Avg", align: "right", render: (r) => formatCurrency(r.avg_price) },
		{
			key: "price_spread_pct",
			label: "Spread",
			align: "right",
			render: (r) =>
				r.price_spread_pct == null ? (
					"—"
				) : (
					<span className={r.price_spread_pct >= 20 ? "font-semibold text-danger" : ""}>
						{r.price_spread_pct}%
					</span>
				),
		},
		{
			key: "in_stock_pct",
			label: "In stock",
			align: "right",
			render: (r) => (r.in_stock_pct == null ? "—" : `${r.in_stock_pct}%`),
		},
	];

	return (
		<Card title={keyword ? `SKU price & stock — “${keyword}”` : "SKU price & stock across stores"}>
			{isLoading ? (
				<Loading label="Loading SKUs…" />
			) : error ? (
				<ErrorState message={error.message} onRetry={refetch} />
			) : rows.length === 0 ? (
				<EmptyState message="No own listings in this window." />
			) : (
				<DataTable
					columns={columns}
					rows={rows}
					rowKey={(r) => r.sku}
					maxHeight={400}
					minWidth={820}
				/>
			)}
		</Card>
	);
};
