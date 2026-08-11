import { MetricTile } from "../../../components/ui/MetricTile";
import { formatCompactCurrency, formatNumber } from "../../../lib/format";

/**
 * One plum for every sparkline. The tiles are a set — six different hues read as
 * six unrelated metrics, and colour here carries no meaning the label doesn't
 * already give. The featured tile flips to white on its filled card.
 */
const SPARK = "#8b6383";
const SPARK_ON_FEATURED = "#ffffff";

/** "2026-08-08" -> "Aug 8". */
const shortDate = (iso) => {
	if (!iso) return null;
	const d = new Date(iso);
	return Number.isNaN(d)
		? null
		: d.toLocaleDateString("en-GB", { month: "short", day: "numeric" });
};

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
	// The window the sparkline covers, captioned under it.
	const first = shortDate(trends[0]?.date);
	const last = shortDate(trends[trends.length - 1]?.date);
	const seriesLabel = first && last ? `${first} – ${last}` : undefined;
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
			sparkColor: SPARK,
		},
		{
			label: "Ad Revenue",
			value: formatCompactCurrency(m("ad_sales").value),
			delta: m("ad_sales").delta_pct,
			series: series((t) => t.ad_sales),
			sparkColor: SPARK,
		},
		{
			// The headline of the ad plane — filled, so the eye lands here first.
			label: "Ad RoAS",
			value: formatRoas(m("roas").value),
			delta: m("roas").delta_pct,
			series: roasSeries,
			sparkColor: SPARK_ON_FEATURED,
			tone: "featured",
		},
		// Sales plane (seller dashboard) ──────────────────────────────
		{
			label: "Total Revenue",
			value: formatCompactCurrency(m("revenue").value),
			delta: m("revenue").delta_pct,
			series: series((t) => t.revenue),
			sparkColor: SPARK,
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
			sparkColor: SPARK,
		},
		{
			// Units are discrete counts, so bars rather than a smoothed line.
			label: "Units sold",
			value: formatNumber(m("units_sold").value),
			delta: m("units_sold").delta_pct,
			series: series((t) => t.units),
			sparkColor: SPARK,
			seriesType: "bar",
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
					seriesType={t.seriesType}
					seriesLabel={seriesLabel}
					tone={t.tone}
				/>
			))}
		</div>
	);
};
