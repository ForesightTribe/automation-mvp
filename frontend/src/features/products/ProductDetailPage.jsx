import { Link, useParams } from "react-router-dom";
import { useProductDetail } from "./hooks";
import { StatusBadge } from "./components/StatusBadge";
import { SalesStockChart } from "./components/SalesStockChart";
import { FacilityStock } from "./components/FacilityStock";
import { CityBreakdown } from "./components/CityBreakdown";
import { PoHistory } from "./components/PoHistory";
import { ProductPublicPanel } from "./components/ProductPublicPanel";
import { MetricTile } from "../../components/ui/MetricTile";
import { Loading } from "../../components/feedback/Loading";
import { ErrorState } from "../../components/feedback/ErrorState";
import { formatCompactCurrency, formatNumber } from "../../lib/format";

const coverLabel = (v) => (v === null || v === undefined ? "—" : `${v} days`);

/**
 * Product 360 — one SKU's full picture: headline KPIs, the sales-vs-stock trend,
 * where it sells (facilities + cities) and its PO supply history. All driven by
 * the single `products/{item_id}` detail call; the PO tab paginates on its own.
 */
export const ProductDetailPage = () => {
	const { itemId } = useParams();
	const { data, isLoading, error, refetch } = useProductDetail(itemId);

	return (
		<div className="flex flex-col gap-6">
			<div>
				<Link
					to="/products"
					className="text-sm text-content-muted hover:text-content"
				>
					← Products
				</Link>
			</div>

			{isLoading && <Loading label="Loading product…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}

			{!isLoading && !error && data && (
				<>
					<div className="flex flex-wrap items-start justify-between gap-3">
						<div>
							<div className="flex items-center gap-3">
								<h1 className="font-display text-xl font-bold text-content">
									{data.item_name || data.item_id}
								</h1>
								<StatusBadge status={data.status} />
							</div>
							<p className="text-sm text-content-muted">
								{data.item_id}
								{data.category ? ` · ${data.category}` : ""}
							</p>
						</div>
					</div>

					<div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
						<MetricTile
							label="Revenue"
							value={formatCompactCurrency(data.revenue)}
						/>
						<MetricTile
							label="Units sold"
							value={formatNumber(data.units_sold)}
						/>
						<MetricTile
							label="Avg price/unit"
							value={formatCompactCurrency(data.avg_price)}
						/>
						<MetricTile
							label="Frontend stock"
							value={formatNumber(data.stock?.frontend_qty)}
						/>
						<MetricTile
							label="Days of cover"
							value={coverLabel(data.days_of_cover)}
						/>
						<MetricTile
							label="Potential loss"
							value={
								data.potential_loss === null
									? "—"
									: formatCompactCurrency(data.potential_loss)
							}
						/>
					</div>

					<SalesStockChart detail={data} />

					<ProductPublicPanel itemId={data.item_id} />

					<div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
						<FacilityStock facilities={data.facilities} />
						<CityBreakdown cities={data.cities} />
					</div>

					<PoHistory itemId={data.item_id} />
				</>
			)}
		</div>
	);
};
