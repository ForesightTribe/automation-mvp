import { MetricTile } from "../../../components/ui/MetricTile";
import { formatCompactCurrency, formatNumber } from "../../../lib/format";

/**
 * KPI strip for the Products list. Reads the `summary` block the list endpoint
 * returns (scoped to the current search/window, independent of pagination and the
 * status drill-down): catalogue size, revenue, units, avg price, plus the two
 * attention counts (out-of-stock, low-cover). No deltas — the list summary is a
 * single-window rollup, not a period-over-period metric.
 */
export const ProductsKpiStrip = ({ summary }) => {
	const s = summary ?? {};
	const tiles = [
		{ label: "Active SKUs", value: formatNumber(s.active_skus) },
		{ label: "Revenue", value: formatCompactCurrency(s.revenue) },
		{ label: "Units sold", value: formatNumber(s.units_sold) },
		{ label: "Avg price/unit", value: formatCompactCurrency(s.avg_price) },
		{
			label: "Out of stock",
			value: formatNumber(s.out_of_stock),
			tone: "danger",
		},
		{
			label: "Low cover",
			value: formatNumber(s.low_cover),
			tone: "warning",
		},
	];
	return (
		<div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
			{tiles.map((t) => (
				<MetricTile
					key={t.label}
					label={t.label}
					value={t.value}
					tone={t.tone}
				/>
			))}
		</div>
	);
};
