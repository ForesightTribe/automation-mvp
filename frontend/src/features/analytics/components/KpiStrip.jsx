import { MetricTile } from "../../../components/ui/MetricTile";
import { formatCompactCurrency, formatNumber } from "../../../lib/format";

/** RoAS like "4.2x" (null -> em dash). */
const formatRoas = (v) =>
	v === null || v === undefined ? "—" : `${v.toFixed(2)}x`;

/**
 * Avg selling price per unit = revenue ÷ units, derived from the two metrics so
 * it carries its own period-over-period delta. Returns a { value, delta_pct }
 * shaped like the API metrics so it drops into a tile unchanged.
 */
const deriveAsp = (revenue, units) => {
	const div = (r, u) => (r != null && u ? r / u : null);
	const value = div(revenue?.value, units?.value);
	const prev = div(revenue?.prev, units?.prev);
	const delta_pct = value != null && prev ? (value - prev) / prev : null;
	return { value, delta_pct };
};

/**
 * Headline KPIs for Sales & Analytics. Sales-plane numbers (revenue, units, SKUs,
 * avg price) sit alongside the blended ad read (spend, RoAS) so the page answers
 * "where is revenue coming from, and is the spend pulling its weight". Each metric
 * is a { value, prev, delta_pct } from analytics/overview; sparklines come from
 * the daily trends series.
 */
export const KpiStrip = ({ data, trends = [] }) => {
	const m = (key) => data?.[key] ?? {};
	const series = (fn) => trends.map(fn);
	const asp = deriveAsp(m("revenue"), m("units_sold"));
	const roasSeries = series((t) =>
		t.ad_spend ? t.ad_sales / t.ad_spend : null,
	);

	const tiles = [
		{
			label: "Total Revenue",
			value: formatCompactCurrency(m("revenue").value),
			delta: m("revenue").delta_pct,
			series: series((t) => t.revenue),
			sparkColor: "#0284c7",
		},
		// {
		// 	label: "Organic Revenue",
		// 	value: formatCompactCurrency(m("organic_revenue").value),
		// 	delta: m("organic_revenue").delta_pct,
		// 	series: series((t) =>
		// 		t.revenue != null && t.ad_sales != null
		// 			? Math.max(0, t.revenue - t.ad_sales)
		// 			: null,
		// 	),
		// 	sparkColor: "#0d9488",
		// },
		{
			label: "Units sold",
			value: formatNumber(m("units_sold").value),
			delta: m("units_sold").delta_pct,
			series: series((t) => t.units),
			sparkColor: "#d97706",
		},
		{
			label: "Active SKUs",
			value: formatNumber(m("distinct_skus").value),
			delta: m("distinct_skus").delta_pct,
		},
		{
			label: "Avg price/unit",
			value: formatCompactCurrency(asp.value),
			delta: asp.delta_pct,
		},
		// {
		// 	label: "Ad Spend",
		// 	value: formatCompactCurrency(m("ad_spend").value),
		// 	delta: m("ad_spend").delta_pct,
		// 	series: series((t) => t.ad_spend),
		// 	sparkColor: "#4f46e5",
		// },
		// {
		// 	label: "Ad RoAS",
		// 	value: formatRoas(m("roas").value),
		// 	delta: m("roas").delta_pct,
		// 	series: roasSeries,
		// 	sparkColor: "#16a34a",
		// },
	];

	return (
		<div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
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
