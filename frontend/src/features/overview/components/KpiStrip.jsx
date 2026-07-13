import { MetricTile } from "../../../components/ui/MetricTile";
import { formatCompactCurrency, formatNumber } from "../../../lib/format";

/** RoAS like "4.2x" (null -> em dash). */
const formatRoas = (v) =>
	v === null || v === undefined ? "—" : `${v.toFixed(2)}x`;

/**
 * Headline KPI tiles for the Overview. Each metric is a { value, prev, delta_pct }
 * object from analytics/overview, aggregated across the selected marketplaces and
 * date range. Two rows of three: the ad plane (spend, revenue, RoAS) above the
 * sales plane (total, organic, units). Market-plane metrics (visibility, avg rank)
 * live on the Competition page.
 */
export const KpiStrip = ({ data, trends = [] }) => {
	const m = (key) => data?.[key] ?? {};
	const series = (fn) => trends.map(fn);
	const roasSeries = series((t) =>
		t.ad_spend ? t.ad_sales / t.ad_spend : null,
	);

	const tiles = [
		// Ad plane (marketing dashboard) ─────────────────────────────
		{
			label: "Ad Spend",
			value: formatCompactCurrency(m("ad_spend").value),
			delta: m("ad_spend").delta_pct,
			series: series((t) => t.ad_spend),
			sparkColor: "#4f46e5",
		},
		{
			label: "Ad Revenue",
			value: formatCompactCurrency(m("ad_sales").value),
			delta: m("ad_sales").delta_pct,
			series: series((t) => t.ad_sales),
			sparkColor: "#16a34a",
		},
		{
			label: "Ad RoAS",
			value: formatRoas(m("roas").value),
			delta: m("roas").delta_pct,
			series: roasSeries,
			sparkColor: "#4f46e5",
		},
		// Sales plane (seller dashboard) ──────────────────────────────
		{
			label: "Total Revenue",
			value: formatCompactCurrency(m("revenue").value),
			delta: m("revenue").delta_pct,
			series: series((t) => t.revenue),
			sparkColor: "#0284c7",
		},
		{
			label: "Organic Revenue",
			value: formatCompactCurrency(m("organic_revenue").value),
			delta: m("organic_revenue").delta_pct,
			series: series((t) =>
				t.revenue != null && t.ad_sales != null
					? Math.max(0, t.revenue - t.ad_sales)
					: null,
			),
			sparkColor: "#0d9488",
		},
		{
			label: "Units sold",
			value: formatNumber(m("units_sold").value),
			delta: m("units_sold").delta_pct,
			series: series((t) => t.units),
			sparkColor: "#d97706",
		},
	];

	return (
		<div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
			{tiles.map((t) => (
				<MetricTile
					key={t.label}
					label={t.label}
					value={t.value}
					delta={t.delta}
					series={t.series}
					sparkColor={t.sparkColor}
				/>
			))}
		</div>
	);
};
